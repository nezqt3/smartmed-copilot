import { useEffect, useState } from "react";
import { api } from "./api";
import { LanguageSwitcher, useI18n, translate, currentLocale } from "./i18n";
import { FactReview } from "./components/FactReview";
import { TranscriptEditor } from "./components/TranscriptEditor";
import {
  EXAMPLE_TURNS,
  FIELD_NAMES,
  type Draft,
  type Extraction,
  type Turn,
} from "./types";

const emptyTurn: Turn = { turn_id: 1, speaker: "patient", text: "" };

function validateTurns(turns: Turn[]): string | null {
  const filled = turns.filter((turn) => turn.text.trim());
  if (filled.length !== turns.length) return translate('请填写或删除空白发言。', currentLocale());
  if (!filled.some((turn) => turn.speaker === "patient"))
    return translate('至少需要一句患者发言。', currentLocale());
  if (turns.reduce((sum, turn) => sum + turn.text.length, 0) > 8000)
    return translate('对话不能超过 8000 个字符。', currentLocale());
  return null;
}

function validateDocument(document: Extraction, turns: Turn[]): string | null {
  const patient = new Map(
    turns
      .filter((turn) => turn.speaker === "patient")
      .map((turn) => [turn.turn_id, turn.text]),
  );
  for (const name of FIELD_NAMES) {
    const fact = document[name];
    if (fact.status === "unknown") continue;
    if (!fact.evidence.length) return `${translate('请为', currentLocale())} ${translate(name, currentLocale())}: ${translate('添加引文', currentLocale())}`;
    for (const evidence of fact.evidence) {
      if (
        !evidence.quote.trim() ||
        !patient.get(evidence.turn_id)?.includes(evidence.quote)
      ) {
        return `${translate(name, currentLocale())}: ${translate('引文不匹配', currentLocale())}`;
      }
    }
    if (
      fact.status === "present" &&
      (!fact.value.trim() ||
        !fact.evidence.some((item) => item.quote.includes(fact.value)))
    ) {
      return `${translate(name, currentLocale())}: ${translate('数值必须出现在引文中', currentLocale())}`;
    }
  }
  return null;
}

function downloadJson(draft: Draft) {
  const blob = new Blob([JSON.stringify(draft, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `smartmed-draft-${draft.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function App() {
  const {t} = useI18n();
  const [loggedIn, setLoggedIn] = useState(Boolean(sessionStorage.getItem('smartmed_token')));
  const [staffId, setStaffId] = useState('pavel');
  const [passcode, setPasscode] = useState('');
  const [alerts, setAlerts] = useState<{code: string; message: string; requires_acknowledgement: boolean}[]>([]);
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [turns, setTurns] = useState<Turn[]>([emptyTurn]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [document, setDocument] = useState<Extraction | null>(null);
  const [reviewer, setReviewer] = useState(sessionStorage.getItem("smartmed_staff") || "");
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [apiStatus, setApiStatus] = useState<
    "checking" | "ready" | "unavailable"
  >("checking");

  useEffect(() => {
    api
      .health()
      .then((result) =>
        setApiStatus(result.status === "ready" ? "ready" : "unavailable"),
      )
      .catch(() => setApiStatus("unavailable"));
    const id = new URLSearchParams(location.search).get("draft");
    if (id && loggedIn) {
      api
        .getDraft(id)
        .then((result) => {
          setDraft(result);
          setDocument(result.document);
          setTurns(result.turns);
          api.safety(result.id).then(report => setAlerts(report.alerts)).catch(cause => setError(cause.message));
        })
        .catch(() => setError(t('无法通过链接打开草稿，请检查编号和网络连接。')));
    }
  }, [loggedIn]);

  const isDirty =
    draft !== null &&
    document !== null &&
    JSON.stringify(document) !== JSON.stringify(draft.document);
  const totalChars = turns.reduce((sum, turn) => sum + turn.text.length, 0);

  async function run(label: string, task: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await task();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('发生未知错误。'));
    } finally {
      setBusy(null);
    }
  }

  function applyDraft(result: Draft) {
    setDraft(result);
    setDocument(result.document);
    setTurns(result.turns);
    setAcknowledged([]);
    api.safety(result.id).then(result => setAlerts(result.alerts)).catch(cause => setError(cause.message));
    history.replaceState(null, "", `?draft=${encodeURIComponent(result.id)}`);
  }

  function reset() {
    setDraft(null);
    setDocument(null);
    setTurns([emptyTurn]);
    setTranscript("");
    setError("");
    setNotice("");
    history.replaceState(null, "", location.pathname);
  }

  function generate() {
    const problem = validateTurns(turns);
    if (problem) {
      setError(problem);
      return;
    }
    run("generate", async () => {
      const result = await api.createDraft(
        turns.map((turn) => ({ ...turn, text: turn.text.trim() })),
      );
      applyDraft(result);
      setNotice(t('草稿已生成，请核对每个字段及其引文后再确认。'));
    });
  }

  function save() {
    if (!draft || !document) return;
    if (!reviewer.trim()) {
      setError(t('请输入审核人姓名或编号。'));
      return;
    }
    const problem = validateDocument(document, draft.turns);
    if (problem) {
      setError(problem);
      return;
    }
    run("save", async () => {
      applyDraft(await api.saveDraft(draft, document, reviewer.trim()));
      setNotice(t('修改已保存，请审核后确认草稿。'));
    });
  }

  function confirm() {
    if (!draft || !document) return;
    if (!reviewer.trim()) {
      setError(t('请输入审核人姓名或编号。'));
      return;
    }
    if (isDirty) {
      setError(t('请先保存修改。'));
      return;
    }
    run("confirm", async () => {
      applyDraft(await api.confirmDraft(draft, reviewer.trim(), acknowledged));
      setNotice(t('草稿已确认，现在可以下载 JSON。'));
    });
  }

  function exportDraft() {
    if (!draft) return;
    run("export", async () => downloadJson(await api.exportDraft(draft.id)));
  }

  function transcribe(file: File | undefined) {
    if (!file) return;
    if (!/\.wav$/i.test(file.name) || file.size > 5_000_000) {
      setError(t('请选择不超过 5 MB 的 WAV 文件。'));
      return;
    }
    run("audio", async () => {
      const result = await api.transcribe(file);
      setTranscript(result.text);
      setNotice(t('请对照录音核对文本，并手动区分医生与患者发言。'));
    });
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="brand">
          <span>
            <strong>{t('智医病历')}</strong>
            <small>{t('智能门诊病历助手')}</small>
          </span>
        </div>
        <div className="header-right"><LanguageSwitcher/>
          <span className={`service-status ${apiStatus}`}>
            <i />
            {apiStatus === "ready"
              ? t('模型就绪')
              : apiStatus === "checking"
                ? t('检查服务中')
                : t('服务不可用')}
          </span>
          <span className="prototype-tag">{t('本地原型')}</span>
        </div>
      </header>

      {!loggedIn ? <main className="page"><form className="card" onSubmit={event => {
        event.preventDefault();
        run('login', async () => {
          const result = await api.login(staffId, passcode);
          sessionStorage.setItem('smartmed_token', result.access_token);
          sessionStorage.setItem('smartmed_staff', staffId);
          setReviewer(staffId); setPasscode(''); setLoggedIn(true);
        });
      }}><h2>{t('员工登录')}</h2><label>{t('员工编号')}<input value={staffId} onChange={e => setStaffId(e.target.value)} autoComplete="username" /></label><label>{t('密码')}<input type="password" value={passcode} onChange={e => setPasscode(e.target.value)} autoComplete="current-password" /></label><button type="submit" disabled={busy !== null}>{t('登录')}</button>{error && <p role="alert">{error}</p>}</form></main> : <main className="page">
        {alerts.length > 0 && <section className="card"><h2>{t('安全核对')}</h2>{alerts.map(alert => <p key={alert.code}>{alert.requires_acknowledgement && <input type="checkbox" checked={acknowledged.includes(alert.code)} onChange={e => setAcknowledged(e.target.checked ? [...acknowledged, alert.code] : acknowledged.filter(code => code !== alert.code))} />} {alert.message}</p>)}</section>}
        {error && (
          <div className="feedback error" role="alert">
            {error}
            <button
              type="button"
              aria-label={t('关闭提示')}
              onClick={() => setError("")}
            >
              ×
            </button>
          </div>
        )}
        {notice && (
          <div className="feedback success" role="status">
            {notice}
            <button
              type="button"
              aria-label={t('关闭提示')}
              onClick={() => setNotice("")}
            >
              ×
            </button>
          </div>
        )}

        <div className="content-grid">
          <section className="panel conversation-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">{t('数据来源')}</p>
                <h2>{t('就诊对话')}</h2>
              </div>
              <span className="panel-meta">
                {turns.length} {t('句对话')} · {totalChars}/8000 {t('字')}
              </span>
            </div>
            <p className="panel-description">
              {t('输入中文对话，并为每句标明说话人。')}
            </p>
            <TranscriptEditor
              turns={turns}
              onChange={setTurns}
              disabled={Boolean(draft) || Boolean(busy)}
            />
            {!draft && (
              <div className="source-actions">
                <button
                  type="button"
                  className="text-button"
                  disabled={Boolean(busy)}
                  onClick={() => {
                    setTurns(EXAMPLE_TURNS.map((turn) => ({ ...turn })));
                    setError("");
                  }}
                >
                  {t('载入示例')}
                </button>
                <span>{t('或')}</span>
                <label className="upload-button">
                  {t('上传 WAV')}
                  <input
                    type="file"
                    accept=".wav,audio/wav"
                    disabled={Boolean(busy)}
                    onChange={(event) => {
                      transcribe(event.target.files?.[0]);
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>
            )}
            {transcript && !draft && (
              <div className="asr-result">
                <div className="asr-heading">
                  <strong>{t('识别文本')}</strong>
                  <span>{t('尚未区分说话人')}</span>
                </div>
                <textarea
                  aria-label={t('待核对的识别文本')}
                  value={transcript}
                  onChange={(event) => setTranscript(event.target.value)}
                  rows={4}
                />
                <p>
                  {t('请听取录音、修正文字，再将内容分配到上方的医生和患者发言。')}
                </p>
              </div>
            )}
            {!draft ? (
              <div className="panel-footer">
                <span>{t('本地模型 · 中文')}</span>
                <button
                  type="button"
                  className="primary-button"
                  disabled={Boolean(busy)}
                  onClick={generate}
                >
                  {busy === "generate" ? t('正在提取事实…') : t('生成草稿')}{" "}
                  <span>→</span>
                </button>
              </div>
            ) : (
              <div className="panel-footer">
                <span>{t('原始对话已保存于草稿')}</span>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={reset}
                >
                  {t('新建对话')}
                </button>
              </div>
            )}
          </section>

          <section className="panel review-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">{t('人工审核')}</p>
                <h2>{t('病历草稿')}</h2>
              </div>
              {draft && (
                <span className={`state-pill ${draft.state}`}>
                  {draft.state === "confirmed" ? t('已确认') : t('待审核')}
                </span>
              )}
            </div>
            {!draft || !document ? (
              <div className="empty-state">
                <div className="empty-art" aria-hidden="true">
                  <span>01</span>
                  <span>02</span>
                  <span>03</span>
                  <span>04</span>
                  <span>05</span>
                  <span>06</span>
                </div>
                <h3>{t('提取的事实将显示在这里')}</h3>
                <p>{t('先根据对话生成草稿，再核对字段值和患者原话。')}</p>
              </div>
            ) : (
              <>
                <div className="review-summary">
                  <span>
                    {
                      FIELD_NAMES.filter(
                        (name) => document[name].status !== "unknown",
                      ).length
                    }{" "}
                    / 6 {t('项有信息')}
                  </span>
                  <span>{t('数据版本')} {draft.contract_version}</span>
                </div>
                <FactReview
                  draft={draft}
                  document={document}
                  onChange={setDocument}
                />
                <div className="review-actions">
                  <label className="reviewer-field">
                    {t('审核人')}
                    <input
                      value={reviewer}
                      maxLength={100}
                      placeholder={t('姓名或人员编号')}
                      onChange={(event) => setReviewer(event.target.value)}
                    />
                  </label>
                  <div className="action-buttons">
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={!isDirty || Boolean(busy)}
                      onClick={save}
                    >
                      {t('保存修改')}
                    </button>
                    <button
                      type="button"
                      className="primary-button"
                      disabled={
                        Boolean(busy) || isDirty || draft.state === "confirmed"
                      }
                      onClick={confirm}
                    >
                      {busy === "confirm" ? t('正在确认…') : t('确认草稿')}{" "}
                      <span>→</span>
                    </button>
                  </div>
                  {draft.state === "confirmed" && (
                    <button
                      type="button"
                      className="export-button"
                      disabled={Boolean(busy) || isDirty}
                      onClick={exportDraft}
                    >
                      {t('↓ 下载已确认的 JSON')}
                    </button>
                  )}
                  <p>{t('结构校验不能代替临床判断。')}</p>
                </div>
              </>
            )}
          </section>
        </div>
        <footer className="site-footer">
          <span>
            <i className="live-dot" /> {t('本地处理 · 数据不会发送至外部模型')}
          </span>
          <span>{t('智医病历 / 原型 0.1')}</span>
        </footer>
      </main>}
    </div>
  );
}
