export const clone = value => JSON.parse(JSON.stringify(value));
export const DEMO_DATE = '2026-10-14T08:00:00.000Z';

export function emptyConfig(name = '新客服') {
  return {
    goal: '根据授权资料回答访客问题，资料不足时说明情况并转人工。',
    audience: '网站访客', scope: '只回答已审阅资料中的信息，不作未授权承诺。',
    tone: '清晰克制', greeting: `你好，我是${name}。有什么可以帮你？`,
    fallback: '目前的资料还不能回答这个问题，我可以帮你转交人工。',
    handoff: { phrases: ['转人工', '人工客服', 'human'], recipient: '客服收件箱', condition: '用户要求人工，或问题超出资料范围时交接。', resumeMinutes: 30 },
    sources: [], qaItems: [], keyFacts: [], businessRules: [], fields: [],
    flow: [
      { id: 'step-understand', title: '了解问题', instruction: '识别用户当前的问题，必要时澄清。' },
      { id: 'step-answer', title: '依据资料回答', instruction: '引用有效资料；没有依据时说明未知或请求人工。' },
    ],
    routeGraph: null,
    skills: [{ id: 'skill-faq', title: '资料答疑', description: '使用当前授权且已审阅的资料回答问题，说明来源。', exit: '问题已答复，或资料不足需人工承接。' }],
    rules: [
      { id: 'rule-rights', title: '仅使用有效授权资料', description: '缺授权、已过期或已撤回的资料不能用于答复。', scope: 'global', locked: true },
      { id: 'rule-write', title: '确认前不执行业务写入', description: '业务工具执行前核验权限、有效确认、任务代次与幂等键。', scope: 'global', locked: true },
      { id: 'rule-evidence', title: '实际结果需要独立证据', description: '答复生成不等于送达或问题解决；业务写入必须保留结果标识。', scope: 'global', locked: true },
    ],
    tools: [], outcome: { definition: '保留答复与有效资料引用；无依据时说明未知或记录人工交接。', unknown: '没有送达或解决证据时保持未知，不自动标记解决。' },
    materialPolicy: { enabled: false, requireExplicitRequest: true, preferredVariant: 'original', allowOriginalFallback: true, maxCount: 1 },
    model: { connectionId: 'simulation', budget: 2000 },
    widget: { title: '有什么可以帮你？', color: '#0071e3', language: 'zh-CN', timezone: 'Asia/Shanghai', hours: '始终接待', formMode: 'offline', showFaq: true, bookingUrl: '', enabled: true },
    contact: { title: name, description: '欢迎咨询，我们会根据资料回答，必要时交给人工。', blocks: [{ id: 'block-intro', type: 'text', title: '欢迎咨询', body: '在这里了解服务，或开始一次对话。' }], published: false },
    channels: { telegram: false, email: false },
  };
}
export function demoSources() {
  return [
    { id: 'source-course', type: 'FAQ', title: '课程内容', question: '数据分析课程学什么？', answer: '这是虚构的四周入门课程，包含表格分析、基础 SQL 和报告练习。', body: '', url: '', status: 'indexed', rights: true, sourceRef: 'fictional:course-guide-v1', expires: '2027-10-14', revokeNote: '在资料库中撤回', version: 1, fictional: true, error: '' },
    { id: 'source-schedule', type: 'FAQ', title: '上课安排', question: '什么时候上课？', answer: '虚构示例课程每周二、周四晚 19:30 开课，实际服务应替换为有权使用的资料。', body: '', url: '', status: 'indexed', rights: true, sourceRef: 'fictional:schedule-v1', expires: '2027-10-14', revokeNote: '在资料库中撤回', version: 1, fictional: true, error: '' },
    { id: 'source-refund', type: 'FAQ', title: '退费处理范围', question: '可以退款吗？', answer: '本示例不自动承诺退款，具体退费问题交由人工核实。', body: '', url: '', status: 'indexed', rights: true, sourceRef: 'fictional:service-boundary-v1', expires: '2027-10-14', revokeNote: '在资料库中撤回', version: 1, fictional: true, error: '' },
  ];
}
export function makeAgent({ id, name, goal, audience } = {}) {
  const config = emptyConfig(name);
  if (goal) config.goal = goal;
  if (audience) config.audience = audience;
  return { id, name, revision: 1, createdAt: DEMO_DATE, config, manualPaths: {}, versions: [], bindings: { widget: null, contact: null }, checks: { testedRevision: null, approvedRevision: null }, conversations: [] };
}
export function initialState() {
  const agent = makeAgent({ id: 'course-demo', name: '课程咨询客服', goal: '根据虚构课程资料回答课程内容和上课安排；退费问题转人工。' });
  agent.config.sources = demoSources();
  agent.config.audience = '咨询课程的网站访客';
  agent.config.widget.title = '了解适合你的课程';
  agent.config.contact.title = '课程咨询';
  agent.revision = 2;
  agent.versions = [{ id: 'v1', revision: 1, config: clone(agent.config), createdAt: DEMO_DATE, status: 'published', evidence: ['虚构样例 · 本地脚本检查'], label: '初始演示版本' }];
  agent.bindings.widget = 'v1';
  agent.conversations = [
    { id: 'conv-demo', visitor: '模拟访客 01', status: 'ai', generation: 1, requestStatus: 'waiting', unread: 1, messages: [{ role: 'visitor', text: '我想了解课程时间。', time: DEMO_DATE }], summary: '访客希望了解上课时间，未办理预约。' },
  ];
  return {
    schema: 1, agents: [agent], selectedAgentId: agent.id,
    connections: [{ id: 'simulation', name: '脚本演示连接', provider: '本地脚本', model: '固定答复', baseUrl: '', status: 'simulation', streaming: 'simulation', tools: 'mock', cancel: 'simulation', error: '' }],
    runs: [], cases: [], proposals: [], feedback: [],
    ui: {
      page: 'agents', depth: 'overview', section: 'service', assistantOpen: false, sidePanel: 'trial', sideOpen: false, pendingOpen: false, knowledgeTab: 'qa', flowView: 'graph', createMode: 'manual', sourceTab: 'FAQ', sourceForm: false, sourceDetail: null, search: '', filter: 'all',
      trialInput: '', trialMessages: [], trialMode: 'simulation', trialState: 'idle',
      assistant: { prompt: '', scope: 'all', status: 'idle', suggestions: [], baseRevision: null, message: '' },
      readonly: false, navOpen: false, sidebarCollapsed: false, toast: null, activeConversation: 'conv-demo', contactPreview: false, deploymentStep: 0,
      deployment: { status: 'idle', error: '', history: [], backup: null, restore: null, upgrade: null }, widgetChecks: [],
      previewVersionId: null, saveStatus: 'saved', savedAt: DEMO_DATE,
    },
  };
}
