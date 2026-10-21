export type VersionState = 'draft' | 'submitted' | 'rejected' | 'approved' | 'released';
export interface AgentSpec { role: string; goal: string; tone: '清晰克制' | '亲切专业'; model: 'default' | 'gpt-6-sol' | 'gpt-6-luna'; fields: {id: string; label: string; source: '用户提供' | '工具返回'}[]; steps: string[]; exit: string; }
export interface DraftVersion { id: string; parent: string | null; state: VersionState; revision: number; spec: AgentSpec; }
export interface EvalResult { version: string; revision: number; passed: number; total: number; source: 'local_fixture'; improvement: null; }
export interface ChangeProposal { id: string; version: string; source: 'human'; risk: 'low' | 'high'; state: 'pending' | 'rejected' | 'approved'; reason: string; }
export interface Case { id: string; expected: '等待确认' | '已取消' | '成功'; must: string; forbid: string; pool: 'pending' | 'golden'; run: string; }
export interface HumanReview { id: string; run: string; scores: Record<'relevance' | 'clarity' | 'evidence' | 'expression', number>; correction: string; reason: string; }
// 原型存储合同；不是已实现的后端 API。不包含凭据或未决 HardRule 形状。
