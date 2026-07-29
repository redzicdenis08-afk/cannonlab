'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-anvil-cost-xp')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = { schemaVersion: 1, startedAt: new Date().toISOString(), prep: null, before: null, after: null, analysis: null, confirmed: false, fatal: null }

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

async function command (bot, text, delay = 400) {
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
  const message = await commandExpect(phaseBot, `/stacklab anvilsnapshot AttackerBot ${label}`, new RegExp(`STACKLAB ANVIL SNAPSHOT ${label} \\{`), 10000)
  const value = parseJsonMessage(message)
  record('snapshot', value)
  return value
}

async function waitForResult (bot, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const window = bot.currentWindow
    const result = window && window.slots ? window.slots[2] : null
    if (result && result.count > 0) return result
    await sleep(150)
  }
  throw new Error('High-cost anvil result did not become available')
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, attackerBot]
  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival AttackerBot')

    const windowOpen = onceWithTimeout(attackerBot, 'windowOpen', 15000)
    const prepPromise = commandExpect(phaseBot, '/stacklab anvilxpprep AttackerBot', /STACKLAB ANVIL XP PREP \{/, 15000)
    const [, prepMessage] = await Promise.all([windowOpen, prepPromise])
    report.prep = parseJsonMessage(prepMessage)
    await waitForResult(attackerBot)
    await sleep(700)
    report.before = await snapshot(phaseBot, 'before-click')

    let clickError = null
    try {
      await attackerBot.clickWindow(2, 0, 0)
    } catch (error) {
      clickError = String(error.stack || error)
    }
    await sleep(1200)
    report.after = await snapshot(phaseBot, 'after-click')

    const repairCost = Number(report.before.repair_cost)
    const maximumRepairCost = Number(report.before.maximum_repair_cost)
    const xpGain = Number(report.after.enchanting_xp) - Number(report.before.enchanting_xp)
    report.analysis = {
      repairCost,
      maximumRepairCost,
      xpBefore: Number(report.before.enchanting_xp),
      xpAfter: Number(report.after.enchanting_xp),
      xpGain,
      vanillaLevelsBefore: Number(report.before.level),
      vanillaLevelsAfter: Number(report.after.level),
      clickError,
      resultPreview: report.before.result,
      committedTokenAfter: Number(report.after.committed_token_total)
    }
    report.confirmed = Boolean(repairCost >= 40 && maximumRepairCost > repairCost && xpGain >= repairCost * 30 && !clickError)
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'anvil-cost-xp-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'anvil-cost-xp-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab anvil cost XP complete') } catch (_) {}
    }
  }
  if (report.fatal || !report.confirmed) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'anvil-cost-xp-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
