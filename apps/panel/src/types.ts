export const FIELD_NAMES = ['发热', '咳嗽', '症状持续时间', '青霉素过敏', '已用药物', '已用药物剂量'] as const
export type FieldName = (typeof FIELD_NAMES)[number]
export type Speaker = 'doctor' | 'patient'
export type Status = 'present' | 'negated' | 'unknown'

export interface Turn {
  turn_id: number
  speaker: Speaker
  text: string
}

export interface Evidence {
  turn_id: number
  quote: string
}

export type Fact =
  | { status: 'present'; value: string; evidence: Evidence[] }
  | { status: 'negated'; value: null; evidence: Evidence[] }
  | { status: 'unknown'; value: null; evidence: [] }

export type Extraction = Record<FieldName, Fact>

export interface Draft {
  id: string
  version: number
  state: 'requires_review' | 'confirmed'
  contract_version: string
  created_at: string
  updated_at: string
  turns: Turn[]
  document: Extraction
  model_metadata: Record<string, unknown>
  reviewer: string | null
}

export const FIELD_LABELS: Record<FieldName, string> = {
  发热: '发热',
  咳嗽: '咳嗽',
  症状持续时间: '症状持续时间',
  青霉素过敏: '青霉素过敏',
  已用药物: '已用药物',
  已用药物剂量: '已用药物剂量',
}

export const EXAMPLE_TURNS: Turn[] = [
  { turn_id: 1, speaker: 'doctor', text: '哪里不舒服？有发热吗？' },
  { turn_id: 2, speaker: 'patient', text: '我咳嗽两天了，没有发热。' },
  { turn_id: 3, speaker: 'doctor', text: '青霉素过敏吗？吃过什么药？' },
  { turn_id: 4, speaker: 'patient', text: '青霉素过敏情况我不知道。我昨天吃了布洛芬，一次200毫克。' },
]
