// 코어 API 호출 모음. 주소를 여기 한 곳에만 둔다.
import { reactive } from 'vue'

/**
 * 지금 로그인한 사람. 라우터와 화면이 함께 본다.
 * undefined = 아직 확인 전, null = 로그인 안 함, 객체 = 로그인함.
 */
export const session = reactive({ user: undefined })

/**
 * 스케줄이 남긴, 아직 안 본 결과의 수.
 * 대화 화면과 상단 띠가 함께 본다. Dashboard 를 보고 있을 때도 알 수 있어야 한다.
 */
export const notify = reactive({ unread: 0 })

async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', // 세션 쿠키를 함께 보낸다
    ...options,
  })
  if (res.status === 401) {
    // 세션이 끊겼다. 화면이 401 을 각자 처리하지 않도록 여기서 한 번에 정리한다.
    session.user = null
    throw new Error('UNAUTHORIZED')
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.status === 204 ? null : res.json()
}

export const api = {
  // --- 로그인 (비밀번호 없음) ---
  listUsers: () => request('/auth/users'),
  login: (username) => request('/auth/login', { method: 'POST', body: JSON.stringify({ username }) }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  me: () => request('/auth/me'),

  // --- 채팅방 (요구사항 13) ---
  listRooms: () => request('/rooms'),
  createRoom: (body) => request('/rooms', { method: 'POST', body: JSON.stringify(body) }),
  getRoom: (id) => request(`/rooms/${id}`),
  updateRoom: (id, body) => request(`/rooms/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteRoom: (id) => request(`/rooms/${id}`, { method: 'DELETE' }),
  listMessages: (id) => request(`/rooms/${id}/messages`),
  markRead: (id) => request(`/rooms/${id}/read`, { method: 'POST' }),
  // 실행 중인 질문 중단. 여기까지 받은 부분 결과는 서버가 저장한다.
  cancelRun: (id) => request(`/rooms/${id}/run`, { method: 'DELETE' }),

  // --- 에이전트 / 모델 / 워크플로우 (요구사항 17, 18, 11) ---
  listAgents: () => request('/agents'),
  refreshAgents: () => request('/agents/refresh', { method: 'POST' }),
  listModels: () => request('/models'),
  listWorkflows: () => request('/workflows'),

  // --- 워크플로우 편집 (화면에서 원문을 고친다) ---
  getWorkflowSource: (key) => request(`/workflows/${key}/source`),
  validateWorkflow: (source) =>
    request('/workflows/validate', { method: 'POST', body: JSON.stringify({ source }) }),
  saveWorkflow: (key, source, baseMtime) =>
    request(`/workflows/${key}`, {
      method: 'PUT',
      body: JSON.stringify({ source, base_mtime: baseMtime ?? null }),
    }),
  deleteWorkflow: (key) => request(`/workflows/${key}`, { method: 'DELETE' }),

  // --- 스케줄 (요구사항 16) ---
  getSchedule: (id) => request(`/rooms/${id}/schedule`),
  putSchedule: (id, body) =>
    request(`/rooms/${id}/schedule`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteSchedule: (id) => request(`/rooms/${id}/schedule`, { method: 'DELETE' }),
  previewCron: (expr) => request(`/cron/preview?expr=${encodeURIComponent(expr)}`),

  // --- 활용 현황 ---
  insights: (period) => request(`/insights?period=${period}`),
}

/**
 * 대화 스트림을 읽는다. SSE 가 아니라 NDJSON(streamable HTTP)이라
 * EventSource 대신 fetch + ReadableStream 을 쓴다.
 *
 * 청크가 줄 중간에서 잘려 도착할 수 있으므로 개행을 기준으로 버퍼링해야 한다.
 * 이 부분을 빼먹으면 JSON.parse 가 간헐적으로 깨진다.
 */
export async function* streamChat(roomId, message, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ room_id: roomId, message }),
    signal,
  })
  if (res.status === 401) {
    session.user = null
    throw new Error('UNAUTHORIZED')
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let index
    while ((index = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, index).trim()
      buffer = buffer.slice(index + 1)
      if (line) yield JSON.parse(line)
    }
  }
  // 마지막 줄에 개행이 없을 수도 있다.
  if (buffer.trim()) yield JSON.parse(buffer.trim())
}
