import test from 'node:test'
import assert from 'node:assert/strict'
import {
  captchaActionLabel,
  requiresAccountLoginRecovery,
  requiresLoginRecovery,
} from '../src/utils/captchaRecovery.js'

test('安全验证状态仍进入滑块求解，不误判为 Cookie 过期', () => {
  const account = {
    cookieStatus: 0,
    loginStatusCode: 'CAPTCHA_REQUIRED',
    loginStatusMessage: 'WS Token 刷新触发滑块验证，需要人工处理',
  }

  assert.equal(requiresAccountLoginRecovery(account), false)
  assert.equal(captchaActionLabel(account), '滑块求解')
})

test('明确的 Session 过期直接进入重新登录恢复', () => {
  const account = {
    cookieStatus: 0,
    loginStatusCode: 'SESSION_EXPIRED',
    loginStatusMessage: 'Cookie 会话已过期，请重新登录',
  }

  assert.equal(requiresAccountLoginRecovery(account), true)
  assert.equal(captchaActionLabel(account), '恢复登录')
})

test('求解器检测到登录页时启用扫码兜底', () => {
  assert.equal(requiresLoginRecovery({
    errorCode: 'CAPTCHA_SOLVE_FAILED',
    message: 'Cookie Session 已过期，页面被重定向到登录页，请重新扫码登录',
  }), true)
})

test('普通滑块失败允许继续重试', () => {
  assert.equal(requiresLoginRecovery({
    errorCode: 'CAPTCHA_SOLVE_FAILED',
    message: '滑块验证未通过，请稍后重试',
  }), false)
})
