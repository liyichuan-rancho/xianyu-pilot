import test from 'node:test'
import assert from 'node:assert/strict'
import {
  createDefaultOpenSourceConfig,
  createDefaultRuntimeStatus,
  normalizeOpenSourceConfig,
} from '../src/composables/useOpenSourceSettings.js'

test('通用模型默认使用 OpenAI 兼容 API', () => {
  const config = createDefaultOpenSourceConfig()
  assert.equal(config.generalModel.transport, 'openai-compatible')
  assert.equal(config.generalModel.cliPath, '')
})

test('保留本机 CLI 调用方式、命令路径与自定义模型', () => {
  const config = normalizeOpenSourceConfig({
    generalModel: {
      transport: 'codex-cli',
      cliPath: '/opt/homebrew/bin/codex',
      modelName: 'gpt-5.3-codex',
    },
  })

  assert.equal(config.generalModel.transport, 'codex-cli')
  assert.equal(config.generalModel.cliPath, '/opt/homebrew/bin/codex')
  assert.equal(config.generalModel.modelName, 'gpt-5.3-codex')
})

test('运行状态包含两种本机 CLI 的探测结果', () => {
  const status = createDefaultRuntimeStatus()
  assert.equal(status.generalModelCliAvailable, false)
  assert.equal(status.codexCliAvailable, false)
  assert.equal(status.cursorCliAvailable, false)
})
