import test from 'node:test'
import assert from 'node:assert/strict'
import {
  TOKEN_KEY,
  USERNAME_KEY,
  getCachedUsername,
  getToken,
  setAuth,
} from '../src/utils/auth.js'

function storage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  }
}

test('login is always persisted without a remember-login option', () => {
  globalThis.localStorage = storage()
  globalThis.sessionStorage = storage({
    [TOKEN_KEY]: 'stale-session-token',
    [USERNAME_KEY]: 'stale-user',
  })

  setAuth('permanent-token', 'admin')

  assert.equal(globalThis.localStorage.getItem(TOKEN_KEY), 'permanent-token')
  assert.equal(globalThis.localStorage.getItem(USERNAME_KEY), 'admin')
  assert.equal(globalThis.sessionStorage.getItem(TOKEN_KEY), null)
  assert.equal(getToken(), 'permanent-token')
  assert.equal(getCachedUsername(), 'admin')
})
