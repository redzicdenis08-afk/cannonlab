'use strict'

const { spawn } = require('child_process')

const TIMEOUT_MS = Number(process.env.PHASELAB_HARD_TIMEOUT_MS || 180000)
const RUNNER = process.env.PHASELAB_RUNNER || 'runner.js'
const child = spawn(process.execPath, [RUNNER], {
  cwd: __dirname,
  env: process.env,
  stdio: 'inherit'
})

let finished = false

function finish (code) {
  if (finished) return
  finished = true
  clearTimeout(timer)
  process.exit(code)
}

const timer = setTimeout(() => {
  console.error(`[PhaseLab supervisor] ${RUNNER} hard timeout after ${TIMEOUT_MS} ms; terminating bot process`)
  child.kill('SIGTERM')
  setTimeout(() => child.kill('SIGKILL'), 1500).unref()
  setTimeout(() => finish(124), 2500).unref()
}, TIMEOUT_MS)

child.on('exit', (code, signal) => {
  if (signal) {
    console.error(`[PhaseLab supervisor] ${RUNNER} exited from signal ${signal}`)
    finish(code || 1)
    return
  }
  finish(code || 0)
})

child.on('error', error => {
  console.error(`[PhaseLab supervisor] failed to start ${RUNNER}:`, error)
  finish(1)
})

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    if (!finished) child.kill(signal)
    finish(1)
  })
}
