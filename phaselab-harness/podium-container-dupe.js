'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const MODE = process.env.PHASELAB_PODIUM_MODE || 'factions'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || `output-podium-${MODE}`)
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  host: HOST,
  port: PORT,
  version: VERSION,
  mode: MODE,
  claimsVerified: false,
  before: null,
  use: null,
  after: null,
  eventVerdict: null,
  duplicated: false,
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
  bot.on('kicked', reason => record('kicked', { username, reason: String(reason) }))
  bot.on('error', error => record('bot_error', { username, error: String(error.stack || error) }))
  await onceWithTimeout(bot, 'spawn', 45000)
  return bot
}

async function command (bot, text, delay = 450) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 10000) {
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

function chunk (value) {
  return Math.floor(value / 16)
}

async function setupFactions (phaseBot, victimBot, attackerBot, build) {
  const center = {
    x: Number(build.center_x),
    y: Number(build.center_y),
    z: Number(build.center_z)
  }
  const fourth = {
    x: Number(build.fourth_base_x),
    y: Number(build.fourth_base_y),
    z: Number(build.fourth_base_z)
  }
  if (chunk(center.x) === chunk(fourth.x) && chunk(center.z) === chunk(fourth.z)) {
    throw new Error(`Podium and fourth crystal share one chunk: center=${JSON.stringify(center)} fourth=${JSON.stringify(fourth)}`)
  }

  await command(phaseBot, `/execute in minecraft:the_end run tp VictimBot ${center.x + 0.5} ${center.y + 2} ${center.z + 0.5}`, 600)
  await command(victimBot, '/f create Victims', 900)
  await command(phaseBot, '/fa power set VictimBot 100', 500)
  await command(victimBot, '/f claim', 900)

  await command(phaseBot, `/execute in minecraft:the_end run tp AttackerBot ${fourth.x + 0.5} ${fourth.y + 1} ${fourth.z + 0.5}`, 600)
  await command(attackerBot, '/f create Attackers', 900)
  await command(phaseBot, '/fa power set AttackerBot 100', 500)
  await command(attackerBot, '/f claim', 900)

  const witnessMessage = await commandExpect(
    phaseBot,
    '/stacklab podiumclaimsnapshot setup',
    /STACKLAB PODIUM CLAIM WITNESS .*"barrel_tag":"Victims".*"crystal_tag":"Attackers".*"verified":true/,
    10000
  )
  report.claimsVerified = true
  record('claims_verified', { witness: parseJsonMessage(witnessMessage) })
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const victimBot = await connect('VictimBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, victimBot, attackerBot]

  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival VictimBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    const cancelGeneration = MODE === 'factions_cancel'
    await command(phaseBot, `/stacklab cancelportal ${cancelGeneration ? 'true' : 'false'}`)

    const buildMessage = await commandExpect(phaseBot, '/stacklab podiumbuild', /STACKLAB PODIUM BUILD \{/, 15000)
    const build = parseJsonMessage(buildMessage)
    record('podium_build_client', build)

    if (MODE === 'factions' || MODE === 'factions_cancel') {
      await setupFactions(phaseBot, victimBot, attackerBot, build)
    }

    const beforeMessage = await commandExpect(phaseBot, '/stacklab podiumsnapshot before', /STACKLAB PODIUM SNAPSHOT before \{/, 8000)
    report.before = parseJsonMessage(beforeMessage)

    const useMessage = await commandExpect(phaseBot, '/stacklab podiumuse AttackerBot', /STACKLAB PODIUM USE \{/, 15000)
    report.use = parseJsonMessage(useMessage)
    await sleep(4500)

    const afterMessage = await commandExpect(phaseBot, '/stacklab podiumsnapshot after', /STACKLAB PODIUM SNAPSHOT after \{/, 8000)
    report.after = parseJsonMessage(afterMessage)
    report.duplicated = Boolean(
      report.before.barrel_type === 'BARREL' &&
      Number(report.before.barrel_netherite) === 64 &&
      report.after.barrel_type === 'BARREL' &&
      Number(report.after.barrel_netherite) === 64 &&
      Number(report.after.dropped_netherite) >= 64
    )
    report.eventVerdict = report.duplicated ? 'confirmed_arbitrary_container_dupe' : 'not_confirmed'
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'podium-container-dupe-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'podium-container-dupe-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab podium complete') } catch {}
    }
  }

  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'podium-container-dupe-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
