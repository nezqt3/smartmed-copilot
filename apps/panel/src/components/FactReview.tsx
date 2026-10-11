import {
  FIELD_LABELS,
  FIELD_NAMES,
  type Draft,
  type Evidence,
  type Extraction,
  type Fact,
  type FieldName,
  type Status,
} from "../types";

interface Props {
  draft: Draft;
  document: Extraction;
  onChange: (document: Extraction) => void;
}

const STATUS_LABELS: Record<Status, string> = {
  present: "明确存在",
  negated: "明确否认",
  unknown: "未知",
};

export function FactReview({ draft, document, onChange }: Props) {
  const patientTurns = draft.turns.filter((turn) => turn.speaker === "patient");

  function setFact(name: FieldName, fact: Fact) {
    onChange({ ...document, [name]: fact });
  }

  function setStatus(name: FieldName, status: Status) {
    const previous = document[name];
    if (status === "unknown")
      setFact(name, { status, value: null, evidence: [] });
    else if (status === "negated")
      setFact(name, {
        status,
        value: null,
        evidence: previous.evidence.length
          ? previous.evidence
          : [{ turn_id: patientTurns[0]?.turn_id || 1, quote: "" }],
      });
    else
      setFact(name, {
        status,
        value: previous.status === "present" ? previous.value : "",
        evidence: previous.evidence.length
          ? previous.evidence
          : [{ turn_id: patientTurns[0]?.turn_id || 1, quote: "" }],
      });
  }

  function setEvidence(name: FieldName, evidence: Evidence[]) {
    const fact = document[name];
    if (fact.status !== "unknown") setFact(name, { ...fact, evidence });
  }

  return (
    <div className="fact-grid">
      {FIELD_NAMES.map((name, index) => {
        const fact = document[name];
        return (
          <section className="fact-card" key={name}>
            <div className="fact-head">
              <span className="fact-number">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div>
                <h3>{FIELD_LABELS[name]}</h3>
              </div>
              <select
                aria-label={`状态：${FIELD_LABELS[name]}`}
                value={fact.status}
                onChange={(event) =>
                  setStatus(name, event.target.value as Status)
                }
              >
                {Object.entries(STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            {fact.status === "unknown" ? (
              <p className="unknown-copy">
                对话中没有可确认的信息。
              </p>
            ) : (
              <>
                {fact.status === "present" && (
                  <label className="field-label">
                    原话中的值
                    <input
                      value={fact.value}
                      maxLength={2000}
                      placeholder="填写患者原话中的连续片段"
                      onChange={(event) =>
                        setFact(name, { ...fact, value: event.target.value })
                      }
                    />
                  </label>
                )}
                <div className="evidence-title">
                  患者引文 <span>须与原话一致</span>
                </div>
                {fact.evidence.map((item, evidenceIndex) => (
                  <div className="evidence-row" key={evidenceIndex}>
                    <select
                      aria-label={`对应的患者发言：${FIELD_LABELS[name]}`}
                      value={item.turn_id}
                      onChange={(event) =>
                        setEvidence(
                          name,
                          fact.evidence.map((entry, i) =>
                            i === evidenceIndex
                              ? {
                                  ...entry,
                                  turn_id: Number(event.target.value),
                                  quote: "",
                                }
                              : entry,
                          ),
                        )
                      }
                    >
                      {patientTurns.map((turn) => (
                        <option key={turn.turn_id} value={turn.turn_id}>
                          患者 · {turn.turn_id}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label={`引文：${FIELD_LABELS[name]}`}
                      value={item.quote}
                      maxLength={2000}
                      placeholder="选中发言中的原文"
                      onChange={(event) =>
                        setEvidence(
                          name,
                          fact.evidence.map((entry, i) =>
                            i === evidenceIndex
                              ? { ...entry, quote: event.target.value }
                              : entry,
                          ),
                        )
                      }
                    />
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`删除引文：${FIELD_LABELS[name]}`}
                      disabled={fact.evidence.length === 1}
                      onClick={() =>
                        setEvidence(
                          name,
                          fact.evidence.filter((_, i) => i !== evidenceIndex),
                        )
                      }
                    >
                      ×
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="text-button add-evidence"
                  disabled={fact.evidence.length >= 8}
                  onClick={() =>
                    setEvidence(name, [
                      ...fact.evidence,
                      { turn_id: patientTurns[0]?.turn_id || 1, quote: "" },
                    ])
                  }
                >
                  + 添加引文
                </button>
              </>
            )}
          </section>
        );
      })}
    </div>
  );
}
