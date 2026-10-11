import type { Turn } from '../types'

interface Props {
  turns: Turn[]
  disabled: boolean
  onChange: (turns: Turn[]) => void
}

export function TranscriptEditor({ turns, disabled, onChange }: Props) {
  function update(index: number, patch: Partial<Turn>) {
    onChange(turns.map((turn, i) => i === index ? { ...turn, ...patch } : turn))
  }

  return <div className="turn-list">
    {turns.map((turn, index) => <div className="turn" key={turn.turn_id}>
      <div className="turn-index">{String(index + 1).padStart(2, '0')}</div>
      <div className="turn-content">
        <div className="turn-toolbar">
          <select aria-label={`第 ${index + 1} 句的角色`} value={turn.speaker}
            disabled={disabled} onChange={event => update(index, { speaker: event.target.value as Turn['speaker'] })}>
            <option value="doctor">医生</option>
            <option value="patient">患者</option>
          </select>
          <button className="text-button danger-text" type="button" disabled={disabled || turns.length === 1}
            onClick={() => onChange(turns.filter((_, i) => i !== index))}>删除</button>
        </div>
        <textarea aria-label={`第 ${index + 1} 句内容`} rows={2} value={turn.text} disabled={disabled}
          maxLength={2000} placeholder="输入对话内容"
          onChange={event => update(index, { text: event.target.value })} />
      </div>
    </div>)}
    <button type="button" className="add-turn" disabled={disabled || turns.length >= 40}
      onClick={() => onChange([...turns, { turn_id: Math.max(0, ...turns.map(turn => turn.turn_id)) + 1,
        speaker: turns.at(-1)?.speaker === 'doctor' ? 'patient' : 'doctor', text: '' }])}>
      <span>＋</span> 添加一句对话
    </button>
  </div>
}
