'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-treecap-treefeller-cross')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  initial: null,
  trials: [],
  conclusive: false,
  bypassConfirmed: false,
  protectionHeld: false,
  fatal: null
}

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
  const bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username,
    auth: 'offline',
    version: VERSION,
    checkTimeoutInterval: 30000
  })
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
  const message = await commandExpect(
    phaseBot,
    `/stacklab treecapsnapshot ${label}`,
    new RegExp(`STACKLAB TREECAP SNAPSHOT ${label} \\{`),
    10000
  )
  const value = parseJsonMessage(message)
  record('snapshot', value)
  return value
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, attackerBot]
  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    const buildMessage = await commandExpect(
      phaseBot,
      '/stacklab treecapbuild AttackerBot',
      /STACKLAB TREECAP BUILD \{/,
      15000
    )
    report.initial = parseJsonMessage(buildMessage)

    for (let run = 1; run <= 3; run++) {
      const before = await snapshot(phaseBot, `run-${run}-before`)
      const invokeMessage = await commandExpect(
        phaseBot,
        '/stacklab treecapinvoke AttackerBot',
        /STACKLAB TREECAP INVOKE \{/,
        15000
      )
      const invoke = parseJsonMessage(invokeMessage)
      await sleep(6500)
      const after = await snapshot(phaseBot, `run-${run}-after`)

      const xpGain = Number(after.foraging_xp) - Number(before.foraging_xp)
      const totalCancelledGain = Number(after.cancelled_events) - Number(before.cancelled_events)
      const syntheticCancelledGain = Number(after.synthetic_cancelled_events) - Number(before.synthetic_cancelled_events)
      const regularCancelledGain = Number(after.regular_cancelled_events) - Number(before.regular_cancelled_events)
      const protectedBroken = Number(before.protected_logs) - Number(after.protected_logs)
      const treefellerPresent = Number(before.treefeller_level) > 0 && before.treefeller_enchant_id === 'treefeller'
      const treefellerTriggered = regularCancelledGain > 0
      const trialConclusive = Boolean(
        invoke.invoked &&
        treefellerPresent &&
        syntheticCancelledGain > 0 &&
        treefellerTriggered
      )
      const bypass = trialConclusive && protectedBroken > 0
      const held = trialConclusive && protectedBroken === 0

      const trial = {
        run,
        before,
        invoke,
        after,
        xpGain,
        totalCancelledGain,
        syntheticCancelledGain,
        regularCancelledGain,
        protectedBroken,
        treefellerPresent,
        treefellerTriggered,
        conclusive: trialConclusive,
        bypass,
        protectionHeld: held
      }
      report.trials.push(trial)
      record('trial', trial)
    }

    report.conclusive = report.trials.length === 3 && report.trials.every(trial => trial.conclusive)
    report.bypassConfirmed = report.conclusive && report.trials.some(trial => trial.bypass)
    report.protectionHeld = report.conclusive && report.trials.every(trial => trial.protectionHeld)
    report.totalXpGain = report.trials.reduce((sum, trial) => sum + trial.xpGain, 0)
    report.totalSyntheticCancelled = report.trials.reduce((sum, trial) => sum + trial.syntheticCancelledGain, 0)
    report.totalRegularCancelled = report.trials.reduce((sum, trial) => sum + trial.regularCancelledGain, 0)
    report.totalProtectedBroken = report.trials.reduce((sum, trial) => sum + trial.protectedBroken, 0)
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'treecap-treefeller-cross-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'treecap-treefeller-cross-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab Treecapitator Treefeller cross-test complete') } catch (_) {}
    }
  }
  if (report.fatal || !report.conclusive) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'treecap-treefeller-cross-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
