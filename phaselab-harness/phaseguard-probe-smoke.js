'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-phaseguard-smoke')
const transcript = []
const report = { startedAt: new Date().toISOString(), fatal: null, steps: [] }

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

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
  const bot = mineflayer.createBot({ host: HOST, port: PORT, username, auth: 'offline', version: VERSION })
  bot.on('messagestr', message => record('chat', { username, message: String(message) }))
  bot.on('error', error => record('bot_error', { username, error: String(error.stack || error) }))
  bot.on('kicked', reason => record('kicked', { username, reason: String(reason) }))
  await onceWithTimeout(bot, 'spawn', 45000)
  record('spawn', { username, position: bot.entity.position })
  return bot
}

async function command (bot, text, delay = 350) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 8000) {
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

async function main () {
  const phaseBot = await connect('PhaseBot')
  const victimBot = await connect('VictimBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, victimBot, attackerBot]

  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival VictimBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    await command(phaseBot, '/stacklab build', 700)
    await command(phaseBot, '/fill 0 64 -4 32 64 4 minecraft:stone', 700)
    await command(phaseBot, '/effect give AttackerBot minecraft:resistance infinite 255 true')
    await command(phaseBot, '/effect give VictimBot minecraft:resistance infinite 255 true')

    await command(phaseBot, '/tp AttackerBot 8.5 65 0.5')
    await command(attackerBot, '/f create Attackers', 900)
    await commandExpect(phaseBot, '/stacklab factionboost Attackers 100', /STACKLAB FACTION BOOST .*"verified":true/, 8000)
    await commandExpect(phaseBot, '/stacklab claimset Attackers 0 0', /STACKLAB CLAIM SET .*"actual_tag":"Attackers".*"verified":true/, 8000)

    await command(phaseBot, '/tp VictimBot 24.5 65 0.5')
    await command(victimBot, '/f create Victims', 900)
    await commandExpect(phaseBot, '/stacklab factionboost Victims 100', /STACKLAB FACTION BOOST .*"verified":true/, 8000)
    await commandExpect(phaseBot, '/stacklab claimset Victims 1 0', /STACKLAB CLAIM SET .*"actual_tag":"Victims".*"verified":true/, 8000)

    await commandExpect(phaseBot, '/phaseprobe start AttackerBot 180 claim-edge-smoke', /PhaseGuard probe started for AttackerBot/, 8000)
    await command(phaseBot, '/tp AttackerBot 13.25 65 3.0 -90 45', 500)
    await commandExpect(phaseBot, '/stacklab boatuse AttackerBot', /STACKLAB BOAT USE .*"accepted":true/, 9000)
    await commandExpect(phaseBot, '/stacklab vehicleinteract AttackerBot OAK_BOAT', /STACKLAB VEHICLE INTERACT .*"mounted":true.*"vehicle_type":"OAK_BOAT"/, 9000)
    await sleep(1200)

    await command(phaseBot, '/tp @e[type=minecraft:oak_boat,sort=nearest,limit=1] 17.5 65 3.0', 700)
    await sleep(1200)
    await command(phaseBot, '/stacklab vehicledismount AttackerBot', 1200)
    await command(phaseBot, '/stacklab vehiclecheck AttackerBot', 500)
    await command(phaseBot, '/phaseprobe snapshot AttackerBot', 400)
    await command(phaseBot, '/phaseprobe listeners', 400)
    await commandExpect(phaseBot, '/phaseprobe stop AttackerBot', /Stopped probe for AttackerBot/, 8000)

    report.steps.push({ setup: true, mounted: true, crossedClaimEdge: true, stopped: true })
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'phaseguard-smoke-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'phaseguard-smoke-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseGuard smoke complete') } catch {}
    }
  }

  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'phaseguard-smoke-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
