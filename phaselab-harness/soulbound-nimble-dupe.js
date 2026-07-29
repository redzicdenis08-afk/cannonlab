'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-soulbound-nimble-dupe')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = { schemaVersion: 1, startedAt: new Date().toISOString(), attempts: [], confirmed: false, fatal: null }

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

async function connect (username, respawn = true) {
  const bot = mineflayer.createBot({ host: HOST, port: PORT, username, auth: 'offline', version: VERSION, respawn, checkTimeoutInterval: 30000 })
  bot.on('messagestr', message => record('chat', { username, message: String(message) }))
  bot.on('death', () => record('death', { username }))
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
  if (start < 0) throw new Error(`JSON missing: ${message}`)
  return JSON.parse(message.slice(start))
}

async function snapshot (phaseBot, label) {
  const message = await commandExpect(
    phaseBot,
    `/stacklab nimblesnapshot VictimBot KillerBot ${label}`,
    /STACKLAB NIMBLE SNAPSHOT \{/,
    10000
  )
  return parseJsonMessage(message)
}

function hasDuplicateMaterial (snapshot) {
  return Object.values(snapshot.per_material || {}).some(value => Number(value) > 1)
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const victimBot = await connect('VictimBot', false)
  const killerBot = await connect('KillerBot')
  const bots = [phaseBot, victimBot, killerBot]

  try {
    await command(phaseBot, '/gamerule keepInventory false')
    await command(phaseBot, '/difficulty normal')
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival VictimBot')
    await command(phaseBot, '/gamemode survival KillerBot')
    await command(phaseBot, '/fill 8 64 25 20 64 35 minecraft:stone')
    await command(phaseBot, '/fill 8 65 25 20 70 35 minecraft:air')

    for (let run = 1; run <= 3; run++) {
      const prepMessage = await commandExpect(phaseBot, '/stacklab nimbleprep VictimBot KillerBot', /STACKLAB NIMBLE PREP .*"accepted":true/, 12000)
      const prep = parseJsonMessage(prepMessage)
      const before = await snapshot(phaseBot, `run-${run}-before`)
      const death = onceWithTimeout(victimBot, 'death', 12000)
      const killMessage = await commandExpect(phaseBot, '/stacklab nimblekill VictimBot KillerBot', /STACKLAB NIMBLE KILL \{/, 12000)
      const kill = parseJsonMessage(killMessage)
      await death
      await sleep(700)
      const dead = await snapshot(phaseBot, `run-${run}-dead`)
      const spawned = onceWithTimeout(victimBot, 'spawn', 15000)
      victimBot.respawn()
      await spawned
      await sleep(900)
      const after = await snapshot(phaseBot, `run-${run}-after`)
      const duplicated = Number(after.total_armor) > 4 || hasDuplicateMaterial(after)
      const preservedExactly = Number(after.total_armor) === 4 && Number(after.victim_armor) === 4 && Number(after.killer_armor) === 0 && Number(after.ground_armor) === 0 && !hasDuplicateMaterial(after)
      const attempt = { run, prep, before, kill, dead, after, duplicated, preservedExactly, lost: Number(after.total_armor) < 4 }
      report.attempts.push(attempt)
      record('attempt', attempt)
    }
    report.confirmed = report.attempts.some(attempt => attempt.duplicated)
    report.confirmedAttempts = report.attempts.filter(attempt => attempt.duplicated).length
    report.exactPreservationAttempts = report.attempts.filter(attempt => attempt.preservedExactly).length
    report.lossAttempts = report.attempts.filter(attempt => attempt.lost).length
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'soulbound-nimble-dupe-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'soulbound-nimble-dupe-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab Soulbound Nimble complete') } catch (_) {}
    }
  }
  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'soulbound-nimble-dupe-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
