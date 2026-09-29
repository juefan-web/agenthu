# 第三方组件与来源项目许可

本文件说明 OneTHU 使用的**第三方代码与接口结论来源**项目及其许可条件。

本仓库自有代码以 **MIT** 许可开源并**附两条限制**（严禁商业用途；严禁用于对清华大学信息服务的
攻击性访问，如抢课 / 自动预约提交一类插件与脚本），全文见根目录 [LICENSE](../LICENSE)。
**以下第三方许可不受该附加限制的扩张或缩减**，各自按其自带条款执行。

原则：**本项目中使用的开源项目均适用其自带许可证**；下面逐项写明「用了什么、依据什么许可」。
凡涉及「接口结论来源」的项目（未直接取用代码、仅依据其公开实现与实测记录得出结论），
同样在此列明，以便回溯。

---

## 1. thu-info-app / thu-info-lib（`packages/info-lib`）

- 上游：<https://github.com/thu-info-community/thu-info-app>（`packages/thu-info-lib`）
- 上游许可：**MIT**（≤ `06dc3cf0`）→ **Business Source License 1.1**（其后各版本，
  Change Date 为该版本首发满四年，Change License: MIT）
- **分发授权**：THU Info 团队（孙迅，`UNIDY2002@outlook.com`）于 **2026-09-16** 邮件授权
  OneTHU 在**非商业用途**下使用 THU Info 相关最新源代码进行**二次分发**，
  **授权截止 2036-12-31**。邮件原文存档于本目录
  [`AUTHOR-GRANT-THU-INFO-2026-09-16.eml`](./AUTHOR-GRANT-THU-INFO-2026-09-16.eml)，随仓库保管。
  > 授权原文（节选）：「我代表 THU Info 团队授权您的 OneTHU 在非商业用途的情况下使用
  > THU Info 相关最新源代码进行二次分发，授权截止日期：2036 年 12 月 31 日。」
- Vendored 基线：上游 3.17.0（2026-09-16，Release 3.17.0）
- OneTHU 适配层（自有代码，源码中标注 `OneTHU 适配`）：
  - `src/utils/network.ts`：platformFetch 注入——Rust 原生传输（reqwest cookie 仓 +
    原生重定向跟随，语义对齐上游 RN/okhttp）
  - `src/lib/core.ts`：剔除 OpenHarmony `rtn-network-utils` require 块（vite 无法静态解析）
  - `src/lib/cr.ts`：联合类型闭包收窄修复

**边界**：授权仅覆盖非商业用途。若将 OneTHU（或其衍生版本）用于商业用途，或超出
2036-12-31，须另行取得上游许可；上游 BSL 1.1 的条款优先于本文件描述。

## 2. LearnX（<https://github.com/robertying/learnX>）

- 许可：**MIT**，**但附带下列例外条件**（原文照录，中英并列）。

  > LearnX is licensed under the MIT License, except:
  >
  > - you currently or formerly worked for the Tsinghua University Information
  >   Technology Center;
  > - your project receives financial support from any organization related to
  >   Tsinghua University.
  >
  > If any of the above applies, any unauthorized use of the code in this
  > project will be considered as infringement. "Use" as referred to above
  > includes making copies of, modifying, or redistributing the source code or
  > derivatives of the project, regardless of whether it is used for commercial
  > purposes.
  >
  > 中文：您过去或者目前为清华大学信息化技术中心工作；您的项目受到任何与清华大学有关的
  > 机构的经济资助。如果上述任意条件成立，任何未经授权的对本项目中代码的使用将会被认为是
  > 侵权。上文中的「使用」包括对项目的源代码或衍生品制作拷贝、修改、重新分发，无论是否
  > 用作商业用途。
- 本项目中的使用方式：**网络学堂相关子页与部分交互按 learnX 的实现移植**（源码注释中
  标注 `learnX 移植`），另有若干接口结论（courseX 众包课程库、扫码登录等）验证自 learnX
  与其作者的其他公开实现。
- **合规提示**：若您（或本项目的使用方）符合上述任一例外条件，则**不得**在未经授权的情况下
  使用来自 LearnX 的代码或其衍生品；此时请移除相关移植部分，或自行取得作者授权。
  本项目其余自有代码不受该例外约束。

## 3. thu-tok-auto（<https://github.com/…/thu-tok-auto>）

- 许可：**MIT**。
- 本项目中的使用方式：**接口结论来源**——清华 MadModel（校园网免费 DeepSeek）站点的
  登录取 token 语义（`/model-api/auth-login/check`、6 小时 JWT、校外全域 307 弹 SSO）
  依据其公开实现与实测记录定案，见 `apps/desktop/src/state/madmodel.ts` 文件头注释。
  未直接取用其代码。

## 4. yuketang-helper-auto（<https://github.com/…/yuketang-helper-auto>）

- 许可：**MIT**。
- 本项目中的使用方式：**接口结论来源**——雨课堂侧接口与页面结构（作业/试卷叶子类型、
  题干加密字体与响应字段、提交资格位等）在实现与实测中参考了该项目的公开实现。
  未直接取用其代码。

## 5. 其他依赖

`cheerio`、`iconv-lite`、`sm-crypto`、`mammoth`、`xlsx`、`katex`（随包内置于
`apps/desktop/src/vendor/katex`）等 npm 依赖：各自适用其自带许可（多为 MIT / Apache-2.0），
随包分发时保留其许可证与版权声明。

---

## 附：MIT License 全文

以下文本适用于 thu-info-lib 历史版本（≤ `06dc3cf0`）以及上表中以 MIT 许可的组件。

Copyright (c) 2020-present UNIDY2002

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
