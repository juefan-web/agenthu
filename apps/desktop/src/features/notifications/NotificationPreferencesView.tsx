import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { NotificationPreferences } from "@agenthu/contracts";
import { BackendHttpError, type BackendClient, type NotificationPreferencesPatch } from "../../backend/client";
import { errorText } from "../../lib/errors";

/** 主动提醒控制面（契约 §6）：类别开关、免打扰起止（跨午夜合法）、每日
 *  上限的明确数值控件 + 当天已用次数（server-only：sent_count/budget_date/
 *  last_sent_at 只读）。PATCH 携带 expected_version，409 加载最新值重填，
 *  不静默覆盖。文案纪律：不声称「绝不会提醒」，精确显示预算与免打扰规则。 */

interface FormState {
  categories: string[];
  quietEnabled: boolean;
  quietStart: string;
  quietEnd: string;
  dailyBudget: number;
}

function formOf(preferences: NotificationPreferences): FormState {
  return {
    categories: preferences.enabled_categories,
    quietEnabled: preferences.quiet_hours_start !== null && preferences.quiet_hours_end !== null,
    quietStart: preferences.quiet_hours_start ?? "22:00",
    quietEnd: preferences.quiet_hours_end ?? "07:00",
    dailyBudget: preferences.daily_budget,
  };
}

export function NotificationPreferencesView({ backend }: { backend: BackendClient | null }) {
  const queryClient = useQueryClient();
  const preferences = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => backend!.getNotificationPreferences(),
    enabled: !!backend,
  });
  const [form, setForm] = useState<FormState | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  // 表单跟随服务端值初始化/重置；用户编辑期间（或 409 冲突提示在场时）
  // 不覆盖本地状态，避免静默改掉用户正在输入的内容。
  useEffect(() => {
    if (preferences.data && form === null) setForm(formOf(preferences.data));
  }, [preferences.data, form]);

  const save = useMutation({
    mutationFn: (input: { patch: NotificationPreferencesPatch; expectedVersion: number }) =>
      backend!.updateNotificationPreferences(input.patch, input.expectedVersion),
    onSuccess: (row) => {
      setConflict(false);
      setNotice("已保存。");
      queryClient.setQueryData(["notification-preferences"], row);
      setForm(formOf(row));
    },
    onError: (error) => {
      if (error instanceof BackendHttpError && error.status === 409) {
        setConflict(true);
        setNotice(null);
        // 另一端已修改：以服务端最新值重填表单，用户看完再决定（不静默覆盖保存）
        void queryClient.invalidateQueries({ queryKey: ["notification-preferences"] }).then(() => {
          const latest = queryClient.getQueryData<NotificationPreferences>(["notification-preferences"]);
          if (latest) setForm(formOf(latest));
        });
        return;
      }
      setNotice(`保存失败：${errorText(error)}`);
    },
  });

  if (!backend) {
    return <section className="notification-preferences-view"><h2>提醒偏好</h2>
      <p role="status">未连接 Backend：偏好设置不可用。</p>
    </section>;
  }
  if (preferences.isError) {
    return <section className="notification-preferences-view"><h2>提醒偏好</h2>
      <p role="alert">加载失败：{errorText(preferences.error)}</p>
    </section>;
  }
  if (!preferences.data || !form) {
    return <section className="notification-preferences-view"><h2>提醒偏好</h2><p role="status">正在加载…</p></section>;
  }

  const data = preferences.data;
  function patchOf(form: FormState): NotificationPreferencesPatch {
    return {
      timezone: data.timezone,
      enabled_categories: form.categories,
      quiet_hours_start: form.quietEnabled ? form.quietStart : null,
      quiet_hours_end: form.quietEnabled ? form.quietEnd : null,
      daily_budget: form.dailyBudget,
    };
  }

  const budgetInvalid = !Number.isInteger(form.dailyBudget) || form.dailyBudget < 0;
  const quietInvalid = form.quietEnabled && (!form.quietStart || !form.quietEnd);

  return <section className="notification-preferences-view">
    <h2>提醒偏好</h2>
    {conflict && <p role="alert">已在其他设备修改：已加载最新值，请确认后再保存（不会静默覆盖）。</p>}
    {notice && <p role="status">{notice}</p>}
    <p className="field-label">
      今天已发送 {data.sent_count} 条 / 上限 {data.daily_budget} 条（时区 {data.timezone}
      {data.last_sent_at ? `，最近发送 ${new Date(data.last_sent_at).toLocaleString()}` : ""}）。
      免打扰时段与每日上限之外的提醒规则以服务端为准。
    </p>
    <form className="notification-preferences-form" onSubmit={(event) => {
      event.preventDefault();
      if (budgetInvalid || quietInvalid || save.isPending) return;
      save.mutate({ patch: patchOf(form), expectedVersion: data.version });
    }}>
      <fieldset>
        <legend>提醒类别</legend>
        <p className="field-label">类别词汇由服务端的主动规则定义；列表为空表示全部关闭。</p>
        <div className="category-chips">
          {form.categories.map((category) => <span key={category} className="category-chip">
            {category}
            <button type="button" title="移除类别" onClick={() =>
              setForm({ ...form, categories: form.categories.filter((item) => item !== category) })}>×</button>
          </span>)}
        </div>
        <CategoryInput onAdd={(category) => {
          if (!form.categories.includes(category)) setForm({ ...form, categories: [...form.categories, category] });
        }} />
      </fieldset>
      <fieldset>
        <legend>免打扰时段</legend>
        <label><input type="checkbox" checked={form.quietEnabled}
          onChange={(event) => setForm({ ...form, quietEnabled: event.target.checked })} /> 启用免打扰（跨午夜合法，如 22:00 → 07:00）</label>
        {form.quietEnabled && <div>
          <label>开始 <input type="time" value={form.quietStart}
            onChange={(event) => setForm({ ...form, quietStart: event.target.value })} /></label>
          <label>结束 <input type="time" value={form.quietEnd}
            onChange={(event) => setForm({ ...form, quietEnd: event.target.value })} /></label>
          {quietInvalid && <p role="alert">免打扰需要同时给出开始与结束时间。</p>}
        </div>}
      </fieldset>
      <fieldset>
        <legend>每日提醒上限</legend>
        <label><input type="number" min={0} step={1} value={form.dailyBudget}
          onChange={(event) => setForm({ ...form, dailyBudget: Number(event.target.value) })} /> 条/天（0 = 不主动提醒）</label>
        {budgetInvalid && <p role="alert">上限必须是不小于 0 的整数。</p>}
      </fieldset>
      <button type="submit" className="primary" disabled={save.isPending || budgetInvalid || quietInvalid}>保存</button>
    </form>
  </section>;
}

function CategoryInput({ onAdd }: { onAdd: (category: string) => void }) {
  const [value, setValue] = useState("");
  return <div className="category-add">
    <input aria-label="新增类别" value={value} placeholder="如 deadline_risk" onChange={(event) => setValue(event.target.value)} />
    <button type="button" disabled={!value.trim()} onClick={() => { onAdd(value.trim()); setValue(""); }}>添加类别</button>
  </div>;
}
