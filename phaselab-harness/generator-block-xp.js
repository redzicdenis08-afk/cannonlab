'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-generator-block-xp')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = { schemaVersion: 1, startedAt: new Date().toISOString(), modes: {}, confirmed: false, fatal: null }

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
  const message = await commandExpect(phaseBot, `/stacklab generatorsnapshot AttackerBot ${label}`, new RegExp(`STACKLAB GENERATOR SNAPSHOT ${label} \\{`), 10000)
  const value = parseJsonMessage(message)
  record('snapshot', value)
  return value
}

async function runCycle (phaseBot, mode, cycle) {
  const resetMessage = await commandExpect(phaseBot, `/stacklab generatorreset AttackerBot ${mode}`, /STACKLAB GENERATOR RESET \{/, 12000)
  const reset = parseJsonMessage(resetMessage)
  let placement = null
  if (mode === 'control') {
    const placeMessage = await commandExpect(phaseBot, '/stacklab generatorplace AttackerBot', /STACKLAB GENERATOR PLACE \{/, 12000)
    placement = parseJsonMessage(placeMessage)
  }
  const before = await snapshot(phaseBot, `${mode}-${cycle}-before`)
  const breakMessage = await commandExpect(phaseBot, '/stacklab generatorbreak AttackerBot', /STACKLAB GENERATOR BREAK \{/, 12000)
  const breakEvidence = parseJsonMessage(breakMessage)
  await sleep(900)
  const after = await snapshot(phaseBot, `${mode}-${cycle}-after`)
  const xpGain = Number(after.mining_xp) - Number(before.mining_xp)
  const debrisGain = Number(after.total_debris) - Number(before.total_debris)
  const result = {
    cycle, reset, placement, before, breakEvidence, after, xpGain, debrisGain,
    markerExpected: mode === 'generated' ? before.block_placed === false : before.block_placed === true,
    exploited: mode === 'generated' && before.block_type === 'ANCIENT_DEBRIS' && before.block_placed === false && breakEvidence.accepted === true && xpGain > 0 && Number(after.total_debris) >= 1,
    controlled: mode === 'control' && before.block_type === 'ANCIENT_DEBRIS' && before.block_placed === true && breakEvidence.accepted === true && xpGain === 0 && Number(after.total_debris) === 1
  }
  record('cycle_result', { mode, ...result })
  return result
}

async function runMode (phaseBot, mode, cycles) {
  const results = []
  for (let cycle = 1; cycle <= cycles; cycle++) results.push(await runCycle(phaseBot, mode, cycle))
  return {
    mode,
    cycles: results,
    totalXpGain: results.reduce((sum, result) => sum + result.xpGain, 0),
    totalDebrisGain: results.reduce((sum, result) => sum + result.debrisGain, 0),
    allMarkerExpected: results.every(result => result.markerExpected)
  }
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, attackerBot]
  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    await commandExpect(phaseBot, '/stacklab generatorprep AttackerBot generated', /STACKLAB GENERATOR PREP \{/, 15000)
    report.modes.generated = await runMode(phaseBot, 'generated', 3)
    report.modes.control = await runMode(phaseBot, 'control', 2)
    report.confirmed = report.modes.generated.cycles.every(result => result.exploited) && report.modes.control.cycles.every(result => result.controlled)
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'generator-block-xp-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'generator-block-xp-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab generator block XP complete') } catch (_) {}
    }
  }
  if (report.fatal || !report.confirmed) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'generator-block-xp-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
