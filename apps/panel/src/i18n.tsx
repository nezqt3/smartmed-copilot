import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Locale = 'ru' | 'en' | 'zh'
const STORAGE_KEY = 'smartmed_locale'

const translations: Record<string, { ru: string; en: string }> = {
  '旧版六字段 / 历史记录': {ru:'Старая версия: 6 полей',en:'Legacy: six fields'},
  '门诊病历（新版本）': {ru:'Новая амбулаторная карта',en:'New outpatient record'},
  '智医病历': {ru:'SmartMed · Медкарта',en:'SmartMed · Records'},
  '中国普通门诊 · outpatient.v1': {ru:'Амбулаторный приём · outpatient.v1',en:'Outpatient visit · outpatient.v1'},
  '模型就绪': {ru:'Модель готова',en:'Model ready'},
  '模型不可用': {ru:'Модель недоступна',en:'Model unavailable'},
  '退出': {ru:'Выйти',en:'Log out'},
  '员工登录': {ru:'Вход сотрудника',en:'Staff sign in'},
  '医师账号': {ru:'Врач',en:'Clinician'},
  '员工编号': {ru:'ID сотрудника',en:'Staff ID'},
  '密码': {ru:'Пароль',en:'Password'},
  '登录': {ru:'Войти',en:'Sign in'},
  '患者与就诊信息': {ru:'Пациент и приём',en:'Patient and visit'},
  '由登记系统或医生填写，模型不会猜测。未知可留空；导出前请核对。': {ru:'Заполняет врач или регистратура. Модель не угадывает данные. Неизвестное оставьте пустым; проверьте перед экспортом.',en:'Completed by a clinician or registration. The model does not guess. Leave unknown fields blank and review before export.'},
  '姓名': {ru:'Имя',en:'Name'}, '患者编号': {ru:'ID пациента',en:'Patient ID'}, '年龄': {ru:'Возраст',en:'Age'},
  '修改信息': {ru:'Изменить данные',en:'Edit details'}, '现在': {ru:'Сейчас',en:'Now'}, '就诊时间自动填写；科室保存在本机。其他信息可稍后补充。': {ru:'Время подставляется автоматически. Отделение сохраняется на этом устройстве. Остальное можно заполнить позже.',en:'Visit time is filled automatically. Department is saved on this device. Other details can be added later.'}, '核对患者信息': {ru:'Проверить данные пациента',en:'Review patient details'},
  '性别': {ru:'Пол',en:'Sex'}, '未知': {ru:'Неизвестно',en:'Unknown'}, '男': {ru:'Мужской',en:'Male'}, '女': {ru:'Женский',en:'Female'}, '其他': {ru:'Другой',en:'Other'},
  '科室': {ru:'Отделение',en:'Department'}, '初诊 / 复诊': {ru:'Тип приёма',en:'Visit type'}, '未指定': {ru:'Не указан',en:'Unspecified'}, '初诊': {ru:'Первичный',en:'Initial'}, '复诊': {ru:'Повторный',en:'Follow-up'}, '就诊时间': {ru:'Дата и время',en:'Visit date and time'},
  '就诊对话': {ru:'Диалог приёма',en:'Visit conversation'},
  '先核对原文和角色，再生成病历。可逐句录音；多人对话需要手动分句并指定角色。': {ru:'Проверьте текст и роли перед созданием карты. Можно записывать реплики по одной; диалог с несколькими людьми разделите вручную.',en:'Review the transcript and speakers before generating a record. Record one turn at a time; split multi-speaker audio manually.'},
  '录音或上传后自动区分医生和患者；生成前请快速核对。': {ru:'После записи или загрузки модель сама разделит речь врача и пациента. Перед созданием карты быстро проверьте результат.',en:'After recording or upload, the model separates doctor and patient speech. Quickly review the result before generating the record.'},
  '已自动区分医生和患者，请快速核对文本。': {ru:'Реплики врача и пациента распределены автоматически. Быстро проверьте текст.',en:'Doctor and patient turns were assigned automatically. Quickly review the text.'},
  '已自动区分角色，请核对不确定的句子': {ru:'Роли распределены автоматически. Проверьте неуверенные реплики:',en:'Speakers assigned automatically. Review uncertain turns:'},
  '这些句子的角色不确定，请核对': {ru:'Неуверенные роли в репликах:',en:'Uncertain speaker roles in turns:'},
  '自动区分失败后可重试，或手动修正。': {ru:'Автоматическое разделение не удалось. Повторите попытку или исправьте текст вручную.',en:'Automatic speaker assignment failed. Retry or correct the text manually.'},
  '重试自动区分角色': {ru:'Повторить авторазделение',en:'Retry speaker assignment'},
  '对话不能超过160句': {ru:'В диалоге не более 160 реплик.',en:'A conversation can have at most 160 turns.'},
  '载入门诊示例': {ru:'Загрузить пример',en:'Load example'}, '载入复杂对话（合成）': {ru:'Загрузить сложный пример',en:'Load complex example'},
  '演示示例': {ru:'Примеры для демо',en:'Demo examples'},
  '上传 WAV': {ru:'Загрузить WAV',en:'Upload WAV'}, '识别原文': {ru:'Распознанный текст',en:'Recognized text'},
  '先修正识别错误。若有多人说话，请拆成多句，逐句指定角色。': {ru:'Исправьте ошибки распознавания. Если говорили несколько человек, разделите текст на реплики и укажите роли.',en:'Correct recognition errors. If multiple people spoke, split the text into turns and assign speakers.'},
  '识别文字的说话角色': {ru:'Роль говорящего',en:'Speaker role'}, '患者': {ru:'Пациент',en:'Patient'}, '医生': {ru:'Врач',en:'Doctor'}, '家属 / 其他': {ru:'Родственник / другой',en:'Family / other'},
  '加入为一句发言': {ru:'Добавить реплику',en:'Add turn'}, '已核对对话和角色': {ru:'Диалог и роли проверены',en:'Transcript and roles reviewed'},
  '已核对对话原文和每句角色': {ru:'Я проверил текст и роль каждой реплики',en:'I reviewed the transcript and each speaker'},
  '正在处理…': {ru:'Обработка…',en:'Processing…'}, '生成门诊病历': {ru:'Создать медкарту',en:'Generate record'}, '新建记录': {ru:'Новая запись',en:'New record'},
  '门诊病历草稿': {ru:'Черновик медкарты',en:'Draft record'}, '已确认': {ru:'Подтверждено',en:'Confirmed'}, '待审核': {ru:'Ожидает проверки',en:'Review pending'},
  '缺失信息保留未知；医生判断和处置只记录已说出的内容。手动修改保留审核记录。': {ru:'Отсутствующие сведения остаются неизвестными. Оценка и план врача содержат только сказанное в диалоге. Правки сохраняются в истории.',en:'Missing information stays unknown. Assessment and plan contain only stated facts. Manual edits are tracked.'},
  '存在冲突，需要解决': {ru:'Есть противоречие — устраните',en:'Conflict — resolve before review'}, '未记录 / 未知（不代表明确否认）': {ru:'Нет данных / неизвестно (не означает отрицание)',en:'Not recorded / unknown (not an explicit denial)'},
  '明确陈述': {ru:'Подтверждено',en:'Stated'}, '明确否认': {ru:'Отрицается',en:'Denied'}, '不确定 / 怀疑': {ru:'Неуверенно / предположение',en:'Uncertain / suspected'},
  '医生手动修改（不伪造原文引用）': {ru:'Правка врача (без вымышленной цитаты)',en:'Clinician edit (no fabricated quote)'}, '删除条目': {ru:'Удалить пункт',en:'Delete item'}, '＋医生补充': {ru:'＋ Дополнение врача',en:'＋ Clinician addition'},
  '已核对本节内容、来源及缺失信息': {ru:'Я проверил раздел, источники и пропуски',en:'I reviewed this section, its sources and missing data'},
  '已审核患者与就诊信息': {ru:'Пациент и приём проверены',en:'Patient and visit reviewed'}, '已核对患者与就诊信息': {ru:'Я проверил пациента и данные приёма',en:'I reviewed patient and visit details'},
  '保存修改': {ru:'Сохранить правки',en:'Save changes'}, '确认全部病历': {ru:'Подтвердить медкарту',en:'Confirm record'}, '复制病历正文': {ru:'Скопировать текст карты',en:'Copy record text'}, '打印 / 保存 PDF': {ru:'Печать / сохранить PDF',en:'Print / save PDF'}, '下载 JSON（集成用）': {ru:'Скачать JSON (для интеграции)',en:'Download JSON (integration)'},
  '生成后显示九个临床章节和对应原文。': {ru:'После создания появятся девять клинических разделов и цитаты из диалога.',en:'Nine clinical sections and their source quotes will appear after generation.'},
  '主诉': {ru:'Жалобы',en:'Chief complaint'}, '现病史': {ru:'История болезни',en:'History of present illness'}, '既往史': {ru:'Анамнез',en:'Past history'}, '过敏史': {ru:'Аллергологический анамнез',en:'Allergy history'}, '用药史': {ru:'Приём лекарств',en:'Medication history'}, '体格检查': {ru:'Осмотр',en:'Physical examination'}, '辅助检查': {ru:'Исследования',en:'Investigations'}, '初步诊断': {ru:'Предварительный диагноз',en:'Assessment'}, '治疗处理意见': {ru:'План лечения',en:'Treatment plan'},
  '来源': {ru:'Источник',en:'Source'}, '第': {ru:'Реплика',en:'Turn'}, '句': {ru:'',en:''}, '句的角色': {ru:'роль реплики',en:'turn speaker'}, '句内容': {ru:'текст реплики',en:'turn text'}, '生成耗时': {ru:'Создано за',en:'Generated in'}, '秒': {ru:'с',en:'s'}, '审核医师': {ru:'Проверил врач',en:'Reviewed by'},
  '智能门诊病历助手': {ru:'Помощник для амбулаторной карты',en:'Outpatient record assistant'}, '检查服务中': {ru:'Проверка сервиса',en:'Checking service'}, '服务不可用': {ru:'Сервис недоступен',en:'Service unavailable'}, '本地原型': {ru:'Локальный прототип',en:'Local prototype'},
  '安全核对': {ru:'Проверка безопасности',en:'Safety review'}, '关闭提示': {ru:'Закрыть сообщение',en:'Dismiss message'}, '数据来源': {ru:'Источник данных',en:'Data source'}, '人工审核': {ru:'Проверка врачом',en:'Clinician review'}, '病历草稿': {ru:'Черновик медкарты',en:'Draft record'},
  '输入中文对话，并为每句标明说话人。': {ru:'Введите диалог на китайском и укажите говорящего для каждой реплики.',en:'Enter a Chinese conversation and assign a speaker to each turn.'}, '载入示例': {ru:'Загрузить пример',en:'Load example'}, '或': {ru:'или',en:'or'}, '识别文本': {ru:'Распознанный текст',en:'Recognized text'}, '尚未区分说话人': {ru:'Роли ещё не назначены',en:'Speakers not assigned'}, '待核对的识别文本': {ru:'Текст для проверки',en:'Transcript to review'}, '请听取录音、修正文字，再将内容分配到上方的医生和患者发言。': {ru:'Прослушайте запись, исправьте текст и распределите реплики между врачом и пациентом.',en:'Listen to the audio, correct the text and assign turns to doctor and patient.'},
  '本地模型 · 中文': {ru:'Локальная модель · китайский',en:'Local model · Chinese'}, '正在提取事实…': {ru:'Извлечение фактов…',en:'Extracting facts…'}, '生成草稿': {ru:'Создать черновик',en:'Generate draft'}, '原始对话已保存于草稿': {ru:'Исходный диалог сохранён',en:'Original conversation saved'}, '新建对话': {ru:'Новый диалог',en:'New conversation'},
  '提取的事实将显示在这里': {ru:'Извлечённые факты появятся здесь',en:'Extracted facts will appear here'}, '先根据对话生成草稿，再核对字段值和患者原话。': {ru:'Создайте черновик по диалогу, затем проверьте поля и цитаты пациента.',en:'Generate a draft from the conversation, then review the fields and patient quotes.'}, '项有信息': {ru:'полей заполнено',en:'fields populated'}, '数据版本': {ru:'Версия данных',en:'Data version'}, '审核人': {ru:'Проверяющий',en:'Reviewer'}, '姓名或人员编号': {ru:'Имя или ID сотрудника',en:'Name or staff ID'}, '正在确认…': {ru:'Подтверждение…',en:'Confirming…'}, '确认草稿': {ru:'Подтвердить черновик',en:'Confirm draft'}, '↓ 下载已确认的 JSON': {ru:'↓ Скачать подтверждённый JSON',en:'↓ Download confirmed JSON'}, '结构校验不能代替临床判断。': {ru:'Проверка структуры не заменяет клиническое решение.',en:'Structural checks do not replace clinical judgment.'}, '本地处理 · 数据不会发送至外部模型': {ru:'Локальная обработка · данные не уходят во внешнюю модель',en:'Local processing · no data sent to external models'}, '智医病历 / 原型 0.1': {ru:'SmartMed / прототип 0.1',en:'SmartMed / prototype 0.1'},
  '发热': {ru:'Лихорадка',en:'Fever'}, '咳嗽': {ru:'Кашель',en:'Cough'}, '症状持续时间': {ru:'Длительность симптомов',en:'Symptom duration'}, '青霉素过敏': {ru:'Аллергия на пенициллин',en:'Penicillin allergy'}, '已用药物': {ru:'Принятые лекарства',en:'Medications taken'}, '已用药物剂量': {ru:'Дозировка лекарств',en:'Medication dose'}, '明确存在': {ru:'Подтверждено',en:'Present'},
  '对话中没有可确认的信息。': {ru:'В диалоге нет подтверждённых сведений.',en:'No confirmed information in the conversation.'}, '原话中的值': {ru:'Значение из слов пациента',en:'Value from patient’s words'}, '填写患者原话中的连续片段': {ru:'Введите точный фрагмент слов пациента',en:'Enter an exact phrase from the patient'}, '患者引文': {ru:'Цитата пациента',en:'Patient quote'}, '须与原话一致': {ru:'должна совпадать дословно',en:'must match exactly'}, '选中发言中的原文': {ru:'Фрагмент выбранной реплики',en:'Text from selected turn'}, '添加引文': {ru:'Добавить цитату',en:'Add quote'}, '状态': {ru:'Статус',en:'Status'}, '对应的患者发言': {ru:'Реплика пациента',en:'Patient turn'}, '引文': {ru:'Цитата',en:'Quote'}, '删除引文': {ru:'Удалить цитату',en:'Remove quote'},
  '请填写或删除空白发言。': {ru:'Заполните или удалите пустые реплики.',en:'Fill or remove empty turns.'}, '至少需要一句患者发言。': {ru:'Нужна хотя бы одна реплика пациента.',en:'At least one patient turn is required.'}, '对话不能超过 8000 个字符。': {ru:'Лимит диалога — 8000 символов.',en:'Conversation limit is 8000 characters.'}, '发生未知错误。': {ru:'Неизвестная ошибка.',en:'Unknown error.'}, '草稿已生成，请核对每个字段及其引文后再确认。': {ru:'Черновик создан. Проверьте поля и цитаты перед подтверждением.',en:'Draft generated. Review fields and quotes before confirming.'}, '请输入审核人姓名或编号。': {ru:'Укажите имя или ID проверяющего.',en:'Enter the reviewer name or ID.'}, '修改已保存，请审核后确认草稿。': {ru:'Правки сохранены. Проверьте и подтвердите черновик.',en:'Changes saved. Review and confirm the draft.'}, '请先保存修改。': {ru:'Сначала сохраните правки.',en:'Save your changes first.'}, '草稿已确认，现在可以下载 JSON。': {ru:'Черновик подтверждён. Можно скачать JSON.',en:'Draft confirmed. You can download JSON.'}, '请选择不超过 5 MB 的 WAV 文件。': {ru:'Выберите WAV не более 5 МБ.',en:'Choose a WAV file up to 5 MB.'}, '请对照录音核对文本，并手动区分医生与患者发言。': {ru:'Сверьте текст с записью и распределите реплики врача и пациента.',en:'Check the transcript against audio and assign doctor and patient turns.'}, '无法通过链接打开草稿，请检查编号和网络连接。': {ru:'Не удалось открыть черновик по ссылке. Проверьте ID и соединение.',en:'Could not open draft from link. Check the ID and connection.'},
  '句对话': {ru:'реплик',en:'turns'}, '字': {ru:'симв.',en:'chars'}, '请为': {ru:'Добавьте для',en:'Add for'}, '引文不匹配': {ru:'цитата не совпадает с выбранной репликой пациента',en:'quote does not match the selected patient turn'}, '数值必须出现在引文中': {ru:'значение должно содержаться в цитате',en:'value must appear in a quote'}, '服务请求失败': {ru:'Ошибка запроса',en:'Request failed'},
  '录音时长需在 0.2–120 秒之间。': {ru:'Длительность записи должна быть от 0,2 до 120 секунд.',en:'Recording must be between 0.2 and 120 seconds.'},
  '此浏览器不支持麦克风录音，请使用 WAV 上传。': {ru:'Этот браузер не поддерживает запись. Загрузите WAV.',en:'This browser cannot record audio. Upload a WAV file.'},
  '录音失败，请检查麦克风权限后重试。': {ru:'Запись не удалась. Проверьте доступ к микрофону.',en:'Recording failed. Check microphone permission.'},
  '语音识别失败。': {ru:'Не удалось распознать речь.',en:'Speech recognition failed.'}, '请允许浏览器访问麦克风。': {ru:'Разрешите браузеру доступ к микрофону.',en:'Allow browser access to the microphone.'}, '无法启动录音，请检查麦克风。': {ru:'Не удалось начать запись. Проверьте микрофон.',en:'Could not start recording. Check the microphone.'},
  '🎙 开始录音': {ru:'🎙 Начать запись',en:'🎙 Start recording'}, '等待麦克风权限…': {ru:'Ожидание доступа к микрофону…',en:'Waiting for microphone permission…'}, '● 录音中': {ru:'● Запись',en:'● Recording'}, '停止并识别': {ru:'Остановить и распознать',en:'Stop and transcribe'}, '放弃': {ru:'Отменить',en:'Discard'}, '正在识别录音…': {ru:'Распознавание записи…',en:'Transcribing audio…'}, '录音仅发送到本机 ASR；识别后请手动核对文字和说话角色。': {ru:'Запись отправляется только в локальный ASR. Проверьте распознанный текст и роли.',en:'Audio is sent only to local ASR. Review the transcript and speaker roles.'},
  '正在识别并区分角色…': {ru:'Распознавание и разделение речи…',en:'Transcribing and assigning speakers…'},
  '录音在本机识别，角色由本地模型自动区分。请核对结果。': {ru:'Запись распознаётся локально; роли определяет локальная модель. Проверьте результат.',en:'Audio is transcribed locally, and a local model assigns speakers. Review the result.'},
  '删除': {ru:'Удалить',en:'Delete'}, '输入对话内容': {ru:'Введите текст реплики',en:'Enter conversation text'}, '添加一句对话': {ru:'Добавить реплику',en:'Add a turn'},
  '服务错误': {ru:'Ошибка сервиса',en:'Service error'}, '请允许打印窗口': {ru:'Разрешите всплывающее окно для печати',en:'Allow the print window'}, '请先确认已保存的病历': {ru:'Сначала подтвердите сохранённую медкарту',en:'Confirm the saved record first'},
  '已载入32句合成门诊对话，含病史矛盾；并非真实患者病历。': {ru:'Загружен синтетический диалог из 32 реплик с противоречием в анамнезе. Это не данные реального пациента.',en:'Loaded a 32-turn synthetic visit with conflicting history. It is not a real patient record.'},
  '请核对识别文字，并将其加入对应角色的发言。': {ru:'Проверьте распознанный текст и добавьте его к реплике нужного участника.',en:'Review the recognized text and assign it to the right speaker.'},
  '音频最大5 MB': {ru:'Размер аудио не более 5 МБ',en:'Audio limit is 5 MB'}, '请修正识别文字并手动分配到医生、患者或其他发言。': {ru:'Исправьте распознанный текст и назначьте роль: врач, пациент или другой.',en:'Correct the transcript and assign it to doctor, patient or another speaker.'},
  '请填写全部发言，对话最多8000字符': {ru:'Заполните все реплики. Лимит — 8000 символов.',en:'Fill every turn. The limit is 8000 characters.'}, '病历已生成。请核对来源，保存修改后逐节确认。': {ru:'Медкарта создана. Проверьте источники, сохраните правки и подтвердите каждый раздел.',en:'Record generated. Review sources, save edits and confirm each section.'},
  '修改已保存，请重新审核当前版本。': {ru:'Правки сохранены. Проверьте текущую версию заново.',en:'Changes saved. Review the current version again.'}, '已复制已确认的病历正文，可粘贴到医院系统并再次核对。': {ru:'Текст подтверждённой карты скопирован. Вставьте его в медицинскую систему и проверьте ещё раз.',en:'Confirmed record text copied. Paste it into the clinical system and review it again.'},
  '无法连接本地服务，请确认 API 已启动。': {ru:'Нет связи с локальным сервисом. Проверьте, запущен ли API.',en:'Cannot reach the local service. Check that the API is running.'}, '请先核对并解决冲突，再保存和审核病历。': {ru:'Устраните противоречия перед сохранением и проверкой.',en:'Resolve conflicts before saving and reviewing.'}, '请先审核并确认已保存的病历。': {ru:'Проверьте и подтвердите сохранённую медкарту.',en:'Review and confirm the saved record first.'}, '草稿已在其他页面更新，请刷新后重试。': {ru:'Черновик обновлён в другой вкладке. Обновите страницу.',en:'Draft updated in another tab. Refresh and try again.'}, '请检查引文，必须与患者原话完全一致。': {ru:'Проверьте цитату: она должна точно совпадать со словами пациента.',en:'Check the quote: it must exactly match the patient’s words.'},
  '模型正忙，请稍后重试自动区分。': {ru:'Модель занята. Повторите авторазделение чуть позже.',en:'The model is busy. Retry speaker assignment shortly.'},
  '自动区分角色失败，请重试。识别文字已保留。': {ru:'Не удалось распределить роли. Повторите попытку; распознанный текст сохранён.',en:'Speaker assignment failed. Retry; the transcript is preserved.'},
  '自动分角色最多支持1200字；识别文字已保留。': {ru:'Для авторазделения нужно до 1200 символов. Распознанный текст сохранён.',en:'Automatic speaker assignment supports up to 1200 characters. The transcript is preserved.'},
}

export function translate(key: string, locale: Locale): string {
  return locale === 'zh' ? key : translations[key]?.[locale] ?? key
}

function initialLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved === 'en' || saved === 'zh' ? saved : 'ru'
  } catch { return 'ru' }
}

const LanguageContext = createContext<{locale: Locale; setLocale: (locale: Locale) => void}>({locale:'ru',setLocale:()=>{}})

export function LanguageProvider({children}: {children: ReactNode}) {
  const [locale, setLocale] = useState<Locale>(initialLocale)
  useEffect(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : locale
    document.title = translate('智医病历', locale)
    try { localStorage.setItem(STORAGE_KEY, locale) } catch { /* storage may be disabled */ }
  }, [locale])
  return <LanguageContext.Provider value={{locale,setLocale}}>{children}</LanguageContext.Provider>
}

export function useI18n() {
  const {locale,setLocale} = useContext(LanguageContext)
  return {locale,setLocale,t: (key:string) => translate(key,locale)}
}

export function currentLocale(): Locale { return initialLocale() }

export function LanguageSwitcher() {
  const {locale,setLocale} = useI18n()
  return <select className="language-switcher" aria-label={{ru:'Язык интерфейса',en:'Interface language',zh:'界面语言'}[locale]} value={locale} onChange={e=>setLocale(e.target.value as Locale)}>
    <option value="ru">Русский</option><option value="en">English</option><option value="zh">中文</option>
  </select>
}
