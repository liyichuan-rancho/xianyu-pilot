import { accountLoginCode, accountLoginMessage } from './accountAuth.js'

const LOGIN_RECOVERY_CODES = new Set([
  'AUTH_MISSING',
  'CREDENTIAL_MISSING',
  'COOKIE_TOKEN_MISSING',
  'SESSION_EXPIRED',
  'FAIL_SYS_SESSION_EXPIRED',
  'FAIL_BIZ_USER_NOT_LOGIN',
  'CAPTCHA_COOKIE_DECRYPT_FAILED',
  'CAPTCHA_COOKIE_MISSING_FIELDS',
])

const LOGIN_RECOVERY_MESSAGE = /(?:cookie\s*session|登录会话|cookie\s*会话).*(?:过期|失效)|(?:cookie|登录).*(?:解密失败|凭据缺失)|FAIL_SYS_SESSION_EXPIRED|重定向到登录页|请重新扫码|需要重新扫码/i

function errorCodeOf(value) {
  if (!value || typeof value !== 'object') return ''
  return String(
    value.errorCode
      || value.code
      || value.loginStatusCode
      || value.login_status_code
      || '',
  ).trim().toUpperCase()
}

function messageOf(value) {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return ''
  return String(
    value.message
      || value.error
      || value.loginStatusMessage
      || value.login_status_message
      || '',
  )
}

/**
 * 只有明确的会话失效/凭据缺失才切到重新登录。
 * CAPTCHA_REQUIRED 不属于这里：它仍应先尝试滑块求解。
 */
export function requiresLoginRecovery(value) {
  const code = errorCodeOf(value)
  if (LOGIN_RECOVERY_CODES.has(code)) return true
  return LOGIN_RECOVERY_MESSAGE.test(messageOf(value))
}

export function requiresAccountLoginRecovery(account) {
  if (!account) return false
  return requiresLoginRecovery({
    loginStatusCode: accountLoginCode(account),
    loginStatusMessage: accountLoginMessage(account),
  })
}

export function captchaActionLabel(account, solving = false) {
  if (solving) return '求解中'
  return requiresAccountLoginRecovery(account) ? '恢复登录' : '滑块求解'
}
