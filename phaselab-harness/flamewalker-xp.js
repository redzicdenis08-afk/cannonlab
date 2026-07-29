'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-flamewalker-xp')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = { schemaVersion: 1, startedAt: new Date().toISOString(), initial: null, trials: [], confirmed: false, fatal: null }

function record (type, data = {}) {
  const row = { ts: new Date().toISOString(), type, ...data }
  transcript.push(row)
  process.stdout.write(`${JSON.stringify(row)}\n`)
}

function onceWithTimeout (emitter, eventName, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => finish(new Error(`Timeout waiting for ${eventName}`)), timeoutMs)
    const handler = (...args) => finish(null, args)
    function finish (error, value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      emitter.removeListener(eventName, handler)
      if (error) reject(error)
      else resolve(value)
    }
    emitter.once(eventName, handler)
  })
}

async function connect (username) {
  const bot = mineflayer.createBot({ host: HOST, port: PORT, username, auth: 'offline', version: VERSION, checkTimeoutInterval: 30000 })
  bot.on('messagestr', message => record('chat', { username, message: String(message) }))
  bot.on('error', error => record('bot_error', { username, error: String(error.stack || error) }))
  bot.on('kicked', reason => record('kicked', { username, reason: String(reason) }))
  await onceWithTimeout(bot, 'spawn', 45000)
  return bot
}

async function command (bot, text, delay = 450) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 12000) {
  record('command', { username: bot.username, text, expect: String(pattern) })
  return await new Promise((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => finish(new Error(`Timeout waiting for ${pattern} after ${text}`)), timeoutMs)
    const handler = message => {
      const rendered = String(message)
      if (pattern.test(rendered)) finish(null, rendered)
    }
    function finish (error, value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      bot.removeListener('messagestr', handler)
      if (error) reject(error)
      else resolve(value)
    }
    bot.on('messagestr', handler)
    bot.chat(text)
  })
}

function parseJsonMessage (message) {
  const start = message.indexOf('{')
  if (start < 0) throw new Error(`JSON missing from message: ${message}`)
  return JSON.parse(message.slice(start))
}

async function snapshot (phaseBot, label) {
  const message = await commandExpect(phaseBot, `/stacklab flamesnapshot AttackerBot ${label}`, new RegExp(`STACKLAB FLAME SNAPSHOT ${label} \\{`), 10000)
  const value = parseJsonMessage(message)
  record('snapshot', value)
  return value
}

async function waitFor (phaseBot, label, predicate, timeoutMs = 16000) {
  const deadline = Date.now() + timeoutMs
  let last = null
  let attempt = 0
  while (Date.now() < deadline) {
    last = await snapshot(phaseBot, `${label}-${attempt++}`)
    if (predicate(last)) return last
    await sleep(450)
  }
  throw new Error(`Timeout in ${label}; last=${JSON.stringify(last)}`)
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, attackerBot]
  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    const prepMessage = await commandExpect(phaseBot, '/stacklab flameprep AttackerBot', /STACKLAB FLAME PREP \{/, 15000)
    report.initial = parseJsonMessage(prepMessage)
    await sleep(1000)

    for (let run = 1; run <= 3; run++) {
      const before = await waitFor(phaseBot, `run-${run}-lava-ready`, value => value.block_type === 'LAVA')
      const triggerMessage = await commandExpect(phaseBot, '/stacklab flametrigger AttackerBot', /STACKLAB FLAME TRIGGER \{/, 12000)
      const trigger = parseJsonMessage(triggerMessage)
      const transformed = await waitFor(phaseBot, `run-${run}-magma`, value => value.block_type === 'MAGMA_BLOCK', 5000)
      const breakMessage = await commandExpect(phaseBot, '/stacklab flamebreak AttackerBot', /STACKLAB FLAME BREAK \{/, 12000)
      const breakEvidence = parseJsonMessage(breakMessage)
      await sleep(600)
      const afterBreak = await snapshot(phaseBot, `run-${run}-after-break`)
      const restored = await waitFor(phaseBot, `run-${run}-restored`, value => value.block_type === 'LAVA')
      const xpGain = Number(afterBreak.mining_xp) - Number(before.mining_xp)
      const magmaGain = Number(afterBreak.total_magma) - Number(before.total_magma)
      const trial = {
        run, before, trigger, transformed, breakEvidence, afterBreak, restored, xpGain, magmaGain,
        untracked: transformed.block_placed === false,
        restoredLava: restored.block_type === 'LAVA',
        exploited: Boolean(trigger.invoked === true && trigger.result === true && transformed.block_type === 'MAGMA_BLOCK' && transformed.block_placed === false && breakEvidence.accepted === true && xpGain > 0 && magmaGain >= 1 && restored.block_type === 'LAVA')
      }
      report.trials.push(trial)
      record('trial', trial)
    }
    report.totalXpGain = report.trials.reduce((sum, trial) => sum + trial.xpGain, 0)
    report.totalMagmaGain = report.trials.reduce((sum, trial) => sum + trial.magmaGain, 0)
    report.confirmed = report.trials.length === 3 && report.trials.every(trial => trial.exploited)
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'flamewalker-xp-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'flamewalker-xp-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab Flame Walker XP complete') } catch (_) {}
    }
  }
  if (report.fatal || !report.confirmed) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'flamewalker-xp-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
