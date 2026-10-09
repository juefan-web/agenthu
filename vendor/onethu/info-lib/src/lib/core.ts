import {
    DOUBLE_AUTH_URL,
    GET_COOKIE_URL,
    GITLAB_AUTH_URL,
    GITLAB_LOGIN_URL,
    ID_BASE_URL,
    ID_HOST_URL,
    ID_LOGIN_URL,
    INVOICE_LOGIN_URL,
    LOGIN_URL,
    LOGOUT_URL,
    ROAMING_URL,
    SAVE_FINGER_URL,
    USER_DATA_URL,
    WEB_VPN_ID_BASE_URL,
    WEB_VPN_ID_LOGIN_URL,
    WEB_VPN_OAUTH_LOGIN_URL,
} from "../constants/strings";
import * as cheerio from "cheerio";
import type {InfoHelper} from "../index";
import {clearCookies, getRedirectUrl, uFetch} from "../utils/network";
import {IdAuthError, LibError, LoginError, UrlError} from "../utils/error";
import {sm2} from "sm-crypto";

type RoamingPolicy = "default" | "card" | "cab" | "gitlab" | "id";

const HOST_MAP: { [key: string]: string } = {
    "zhjw.cic": "77726476706e69737468656265737421eaff4b8b69336153301c9aa596522b20bc86e6e559a9b290",
    "jxgl.cic": "77726476706e69737468656265737421faef469069336153301c9aa596522b20e33c1eb39606919f",
    "ecard": "77726476706e69737468656265737421f5f4408e237e7c4377068ea48d546d303341e9882a",
    "learn": "77726476706e69737468656265737421fcf2408e297e7c4377068ea48d546d30ca8cc97bcc",
    "mails": "77726476706e69737468656265737421fdf64890347e7c4377068ea48d546d3011ff591d40",
    "50": "77726476706e69737468656265737421a5a70f8834396657761d88e29d51367b6a00",
    "166.111.14.8": "77726476706e69737468656265737421a1a117d27661391e2f5cc7f4",
    "fa-online": "77726476706e69737468656265737421f6f60c93293c615e7b469dbf915b243daf0f96e17deaf447b4",
    "dzpj": "77726476706e69737468656265737421f4ed519669247b59700f81b9991b2631aee63c51",
    "jjhyhdf": "77726476706e69737468656265737421fafd49852f346e1e6a1b80a29f5d36342bb9c40cf69277",
    "yhdf": "77726476706e69737468656265737421e9ff459a69247b59700f81b9991b26317dbd36ae",
    "usereg": "77726476706e69737468656265737421e5e4448e223726446d0187ab9040227b54b6c80fcd73",
    "thos": "77726476706e69737468656265737421e4ff4e8f69247b59700f81b9991b2631ca359dd4",
};

// 学校 id 登录口令的 SM2 非压缩公钥点前缀（表单协议事实，见 #sm2publicKey 页面脚本）。
const SM2_MAGIC_NUMBER = "04";

const parseUrl = (urlIn: string) => {
    const rawRes = /http:\/\/(\d+.\d+.\d+.\d+):(\d+)\/(.+)/g.exec(urlIn);
    if (rawRes !== null && rawRes[1] !== undefined && rawRes[2] !== undefined && rawRes[3] !== undefined) {
        return `https://webvpn.tsinghua.edu.cn/http-${rawRes[2]}/${HOST_MAP[rawRes[1]]}/${rawRes[3]}`;
    }
    const protocol = urlIn.substring(0, urlIn.indexOf(":"));
    const regRes = /:\/\/(.+?).tsinghua.edu.cn(:(\d+))?\/(.+)/.exec(urlIn);
    if (regRes === null || regRes[1] === undefined || regRes[4] === undefined) {
        throw new UrlError();
    }
    const host = regRes[1];
    const protocolFull = regRes[3] === undefined ? protocol : `${protocol}-${regRes[3]}`;
    const path = regRes[4];
    return `https://webvpn.tsinghua.edu.cn/${protocolFull}/${HOST_MAP[host]}/${path}`;
};

// 把裸 id 域锚点换算成新 LB 入口（oauth lbredirect），平台传输跟随铸票；
// learn 会话即走此链（表单→check→锚点→包装跟随）。
const getWebVPNUrl = (urlIn: string): string => {
    if (urlIn.search("oauth.tsinghua.edu.cn") !== -1) {
        return urlIn;
    }

    const url = new URL(urlIn);
    const scheme = url.protocol.replace(":", "");
    const host = url.hostname;
    const port = url.port || (scheme == "https" ? "443" : "80");
    const uri = url.pathname + (url.search ? url.search : "") + (url.hash ? url.hash : "");
    return `https://oauth.tsinghua.edu.cn/lb-auth/lbredirect?scheme=${scheme}&host=${host}&port=${port}&uri=${uri}`;
};

export const getCsrfToken = async () => {
    const cookie = await uFetch(GET_COOKIE_URL);
    const q = /XSRF-TOKEN=(.+?);/.exec(cookie + ";");
    if (q === null || q[1] === undefined) {
        throw new Error("Failed to get csrf token.");
    }
    return q[1];
};

let outstandingLoginPromise: Promise<void> | undefined = undefined;

const twoFactorAuth = async (helper: InfoHelper): Promise<string> => {
    const approaches = JSON.parse(await uFetch(DOUBLE_AUTH_URL, {
        action: "FIND_APPROACHES",
    }));
    if (approaches.result != "success") {
        throw new LoginError(approaches.msg);
    }
    if (!helper.twoFactorMethodHook) {
        throw new LoginError("Required to select 2FA method");
    }
    const method = await helper.twoFactorMethodHook(
        approaches.object.hasWeChatBool,
        approaches.object.phone,
        approaches.object.hasTotp,
    );
    if (method === undefined) {
        throw new LoginError("2FA required");
    }
    const { result: r2, msg: m2 } = JSON.parse(await uFetch(DOUBLE_AUTH_URL, {
        action: "SEND_CODE",
        type: method,
    }));
    if (r2 != "success") {
        throw new LoginError(m2);
    }
    if (!helper.twoFactorAuthHook) {
        throw new LoginError("2FA required");
    }
    const code = await helper.twoFactorAuthHook();
    if (code === undefined) {
        throw new LoginError("2FA required");
    }
    const verified = JSON.parse(await uFetch(DOUBLE_AUTH_URL, {
        action: method === "totp" ? "VERITY_TOTP_CODE" : "VERITY_CODE",
        vericode: code,
    }));
    if (verified.result != "success") {
        throw new LoginError(verified.msg);
    }
    if (helper.trustFingerprintHook) {
        const trustFingerprint = await helper.trustFingerprintHook();
        if (trustFingerprint) {
            const parsed = JSON.parse(await uFetch(SAVE_FINGER_URL, {
                fingerprint: helper.fingerprint,
                deviceName: await helper.trustFingerprintNameHook(),
                radioVal: "是",
            }));
            const { result: r4, msg: m4 } = parsed;
            if (r4 != "success") {
                if (m4.includes("上限") || m4.includes("limit")) {
                    helper.twoFactorAuthLimitHook && await helper.twoFactorAuthLimitHook();
                }
                else {
                    throw new LoginError(m4);
                }
            }
            else {
                // 响应 object 即 finger3（bundle: saveFinger3Local(t.object)）——
                // 此前被解构丢弃，helper.fingerGenPrint 永远空 → checkSingle 确认
                // 传空指纹 → id 死结（2026-09-18 三次"已增加"实录）
                helper.fingerGenPrint = String(parsed.object ?? "") || helper.fingerGenPrint;
            }
        }
    }
    return await uFetch(ID_HOST_URL + verified.object.redirectUrl);
};

export const login = async (
    helper: InfoHelper,
    userId: string,
    password: string,
): Promise<void> => {
    helper.userId = userId;
    helper.password = password;
    if (helper.userId === "" || helper.password === "") {
        const e = new LoginError("Please login.");
        helper.loginErrorHook && helper.loginErrorHook(e);
        throw e;
    }
    if (!helper.userId.match(/^\d+$/)) {
        const e = new LoginError("请输入学号。");
        helper.loginErrorHook && helper.loginErrorHook(e);
        throw e;
    }
    if (!helper.mocked()) {
        clearCookies();
        await helper.clearCookieHandler();
        if (outstandingLoginPromise === undefined) {
            outstandingLoginPromise = new Promise<void>((resolve, reject) => {
                const timer = setTimeout(() => {
                    reject(new LoginError("Login timeout."));
                }, 3 * 60 * 1000);
                (async () => {
                    await uFetch(WEB_VPN_OAUTH_LOGIN_URL);
                    // OneTHU 适配（2026-09-17 定案）：库外层（infoLib.libLogin）
                    // 已在登录前清空原生 cookie 仓——干净客户端总是走完整
                    // OAuth 舞（表单带 sig → check → 302 webvpn/login?code=
                    // → 铸真票）。带陈旧匿名票才会被 IP 续会拦成门户页
                    // （无 key），此处保持「无 key 即报错」，由外层自愈重试。
                    const landingPage = await uFetch(WEB_VPN_OAUTH_LOGIN_URL);
                    const sm2PublicKey = cheerio.load(landingPage)("#sm2publicKey").text();
                    if (sm2PublicKey === "") {
                        throw new LoginError("Failed to get public key.");
                    }
                    let response = await uFetch(ID_LOGIN_URL, {
                        i_user: helper.userId,
                        i_pass: SM2_MAGIC_NUMBER + sm2.doEncrypt(helper.password, sm2PublicKey),
                        fingerPrint: helper.fingerprint,
                        fingerGenPrint: "",
                        i_captcha: "",
                    });
                    if (response.includes("二次认证")) {
                        response = await twoFactorAuth(helper);
                    }
                    if (!response.includes("登录成功。正在重定向到")) {
                        const $ = cheerio.load(response);
                        const message = $("#msg_note").text().trim();
                        throw new LoginError(message);
                    }
                    const callbackUrl = cheerio.load(response)("a").attr()!.href;
                    const redirectUrl = await getRedirectUrl(callbackUrl);
                    if (redirectUrl === LOGIN_URL || redirectUrl == null) {
                        throw new LoginError("登录失败，请稍后重试。");
                    }
                    await roam(helper, "id", "10000ea055dd8d81d09d5a1ba55d39ad");
                    outstandingLoginPromise = undefined;
                })().then(() => { clearTimeout(timer); resolve(); }, (e: unknown) => {
                    clearTimeout(timer);
                    helper.loginErrorHook && helper.loginErrorHook(e);
                    outstandingLoginPromise = undefined;
                    reject(e);
                });
            });
        }
        await outstandingLoginPromise;
    }
};

/** OneTHU 适配（2026-09-17）：2FA 挂起的登录链（等验证码的 futures）永不清
 *  outstandingLoginPromise——后续 login() 全都 await 这具僵尸，3 分钟后集体
 *  "Login timeout"（真机实录：开机 need-2fa 后手点登录全部无响应）。
 *  外层每次发起全新 libLogin 前调用本函数弃掉旧链（旧 futures 无人等，可 GC）。 */
export const clearOutstandingLogin = (): void => {
    outstandingLoginPromise = undefined;
};

export const logout = async (helper: InfoHelper): Promise<void> => {
    if (!helper.mocked()) {
        helper.userId = "";
        helper.password = "";
        await uFetch(LOGOUT_URL);
    } else {
        helper.userId = "";
        helper.password = "";
    }
};

export const roam = async (helper: InfoHelper, policy: RoamingPolicy, payload: string): Promise<string> => {
    switch (policy) {
    case "default": {
        const csrf = await getCsrfToken();
        const {object} = await uFetch(`${ROAMING_URL}?yyfwid=${payload}&_csrf=${csrf}&machine=p`, {}).then(JSON.parse);
        const url = parseUrl(object.roamingurl.replace(/&amp;/g, "&"));
        if (url.includes(HOST_MAP["dzpj"])) {
            const roamHtml = await uFetch(url);
            const username = /\("username"\).value = '(.+?)';/.exec(roamHtml);
            if (username === null || username[1] === undefined) {
                throw new LibError("Failed to get username when roaming to fa-online");
            }
            const password = /\("password"\).value = '(.+?)';/.exec(roamHtml);
            if (password === null || password[1] === undefined) {
                throw new LibError("Failed to get password when roaming to fa-online");
            }
            return await uFetch(INVOICE_LOGIN_URL, {username: username[1], password: password[1]});
        }
        return await uFetch(url);
    }
    case "id": {
        let response = "";
        for (let i = 0; i < 2; i++) {
            // id 表单页携带 SM2 公钥（#sm2publicKey），口令必须加密上传
            // （sm-crypto 独立实现，见任务书 §0-3）。
            const formPage = await uFetch(ID_BASE_URL + payload);
            const sm2PublicKey = cheerio.load(formPage)("#sm2publicKey").text();
            if (sm2PublicKey === "") {
                throw new LoginError("Failed to get public key.");
            }
            response = await uFetch(ID_LOGIN_URL, {
                i_user: helper.userId,
                i_pass: SM2_MAGIC_NUMBER + sm2.doEncrypt(helper.password, sm2PublicKey),
                fingerPrint: helper.fingerprint,
                fingerGenPrint: helper.fingerGenPrint ?? "",
                i_captcha: "",
            });
            if (response.includes("二次认证")) {
                response = await twoFactorAuth(helper);
            }
            if (response.includes("登录成功。正在重定向到")) {
                break;
            }
        }
        if (!response.includes("登录成功。正在重定向到")) {
            throw new IdAuthError();
        }
        const redirectUrl = getWebVPNUrl(cheerio.load(response)("a").attr()!.href);
        return await uFetch(redirectUrl);
    }
    case "card":
    case "cab": {
        const idBaseUrl = policy === "card" ? ID_BASE_URL : WEB_VPN_ID_BASE_URL;
        const idLoginUrl = policy === "card" ? ID_LOGIN_URL : WEB_VPN_ID_LOGIN_URL;
        let response = "";
        for (let i = 0; i < 2; i++) {
            await uFetch(idBaseUrl + payload);
            response = await uFetch(idLoginUrl, {
                i_user: helper.userId,
                i_pass: helper.password,
                fingerPrint: helper.fingerprint,
                fingerGenPrint: "",
                i_captcha: "",
            });
            if (response.includes("二次认证")) {
                response = await twoFactorAuth(helper);
            }
            if (response.includes("登录成功。正在重定向到")) {
                break;
            }
        }
        if (!response.includes("登录成功。正在重定向到")) {
            throw new IdAuthError();
        }
        const redirectUrl = cheerio.load(response)("a").attr()!.href;

        return await uFetch(redirectUrl);
    }
    case "gitlab": {
        const data = await uFetch(GITLAB_LOGIN_URL);
        if (data.includes("sign_out")) return data;
        const authenticity_token = cheerio.load(data)("[name=authenticity_token]").attr()!.value;
        await uFetch(GITLAB_AUTH_URL, {authenticity_token});
        let response = await uFetch(ID_LOGIN_URL, {
            i_user: helper.userId,
            i_pass: helper.password,
            fingerPrint: helper.fingerprint,
            fingerGenPrint: "",
            i_captcha: "",
        });
        if (response.includes("二次认证")) {
            response = await twoFactorAuth(helper);
        }
        if (!response.includes("登录成功。正在重定向到")) {
            throw new IdAuthError();
        }
        const redirectUrl = cheerio.load(response)("a").attr()!.href;
        return await uFetch(redirectUrl);
    }
    }
};

export const verifyAndReLogin = async (helper: InfoHelper): Promise<boolean> => {
    if (outstandingLoginPromise) {
        await outstandingLoginPromise;
        return true;
    }
    try {
        const {object} = await uFetch(`${USER_DATA_URL}?_csrf=${await getCsrfToken()}`).then(JSON.parse);
        if (object.ryh === helper.userId) {
            return false;
        }
    } catch {
        //
    }
    const {userId, password} = helper;
    await login(helper, userId, password);
    return true;
};

export const roamingWrapper = async <R>(
    helper: InfoHelper,
    policy: RoamingPolicy | undefined,
    payload: string,
    operation: (param?: string) => Promise<R>,
): Promise<R> => {
    if (helper.userId === "" || helper.password === "") {
        const e = new LoginError("Please login.");
        helper.loginErrorHook && helper.loginErrorHook(e);
        throw e;
    }
    try {
        if (policy) {
            try {
                return await operation();
            } catch {
                let result: string;
                try {
                    result = await roam(helper, policy, payload);
                } catch {
                    result = await roam(helper, policy, payload);
                }
                return await operation(result);
            }
        } else {
            return await operation();
        }
    } catch (e) {
        if (await verifyAndReLogin(helper)) {
            if (policy) {
                const result = await roam(helper, policy, payload);
                return await operation(result);
            } else {
                return await operation();
            }
        } else {
            throw e;
        }
    }
};

export const roamingWrapperWithMocks = async <R>(
    helper: InfoHelper,
    policy: RoamingPolicy | undefined,
    payload: string,
    operation: (param?: string) => Promise<R>,
    fallback: R,
): Promise<R> =>
    helper.mocked()
        ? Promise.resolve(fallback)
        : roamingWrapper(helper, policy, payload, operation);
