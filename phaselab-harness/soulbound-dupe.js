'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-soulbound-dupe')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  host: HOST,
  port: PORT,
  version: VERSION,
  scope: 'authorized exact private Sakura stack',
  attempts: [],
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

async function connect (username, respawn = true) {
  const bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username,
    auth: 'offline',
    version: VERSION,
    respawn,
    checkTimeoutInterval: 30000
  })
  bot.on('messagestr', message => record('chat', { username, message: String(message) }))
  bot.on('kicked', reason => record('kicked', { username, reason: String(reason) }))
  bot.on('error', error => record('bot_error', { username, error: String(error.stack || error) }))
  bot.on('death', () => record('client_death', { username }))
  bot.on('respawn', () => record('client_respawn_packet', { username }))
  await onceWithTimeout(bot, 'spawn', 45000)
  record('spawn', { username, position: bot.entity.position })
  return bot
}

async function command (bot, text, delay = 450) {
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

function parseJsonMessage (message) {
  const start = message.indexOf('{')
  if (start < 0) throw new Error(`JSON missing from message: ${message}`)
  return JSON.parse(message.slice(start))
}

async function snapshot (phaseBot, player, label) {
  const message = await commandExpect(
    phaseBot,
    `/stacklab soulboundsnapshot ${player} ${label}`,
    /STACKLAB SOULBOUND SNAPSHOT \{/,
    8000
  )
  const parsed = parseJsonMessage(message)
  record('soulbound_snapshot_client', parsed)
  return parsed
}

async function runAttempt (phaseBot, attackerBot, copies, run) {
  await command(phaseBot, '/kill @e[type=minecraft:item]', 250)
  await command(phaseBot, '/clear AttackerBot', 250)
  await command(phaseBot, '/gamemode survival AttackerBot', 250)
  await command(phaseBot, '/effect clear AttackerBot', 200)
  await command(phaseBot, '/tp AttackerBot 13.5 65 30.5', 350)

  const prepMessage = await commandExpect(
    phaseBot,
    `/stacklab soulboundprep AttackerBot ${copies} full`,
    /STACKLAB SOULBOUND PREP .*"accepted":true/,
    8000
  )
  const prepared = parseJsonMessage(prepMessage)
  const before = await snapshot(phaseBot, 'AttackerBot', `before-${copies}-${run}`)

  const death = onceWithTimeout(attackerBot, 'death', 10000)
  await command(phaseBot, '/kill AttackerBot', 100)
  await death
  await sleep(700)

  const dead = await snapshot(phaseBot, 'AttackerBot', `dead-${copies}-${run}`)
  const spawned = onceWithTimeout(attackerBot, 'spawn', 15000)
  attackerBot.respawn()
  await spawned
  await sleep(900)
  await command(phaseBot, '/tp AttackerBot 13.5 65 30.5', 350)
  const after = await snapshot(phaseBot, 'AttackerBot', `after-${copies}-${run}`)

  const expectedNested = copies * 1728
  const expectedFillerDiamonds = (36 - copies) * 64
  const result = {
    copies,
    run,
    prepared,
    before,
    dead,
    after,
    expectedCopies: copies,
    expectedNested,
    expectedFillerDiamonds,
    duplicated: Number(after.total_copies) > copies || Number(after.total_nested_netherite) > expectedNested || Number(after.total_filler_diamonds) > expectedFillerDiamonds,
    preservedExactly: Number(after.total_copies) === copies && Number(after.total_nested_netherite) === expectedNested && Number(after.total_filler_diamonds) === expectedFillerDiamonds,
    lost: Number(after.total_copies) < copies || Number(after.total_nested_netherite) < expectedNested || Number(after.total_filler_diamonds) < expectedFillerDiamonds
  }
  record('soulbound_attempt', result)
  return result
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot', false)
  const bots = [phaseBot, attackerBot]

  try {
    await command(phaseBot, '/gamerule keepInventory false')
    await command(phaseBot, '/difficulty peaceful')
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/fill 8 64 25 18 64 35 minecraft:stone', 450)
    await command(phaseBot, '/fill 8 65 25 18 70 35 minecraft:air', 450)

    for (const copies of [1, 2]) {
      for (let run = 1; run <= 3; run++) {
        try {
          report.attempts.push(await runAttempt(phaseBot, attackerBot, copies, run))
        } catch (error) {
          const failure = { copies, run, duplicated: false, error: String(error.stack || error) }
          report.attempts.push(failure)
          record('soulbound_attempt_error', failure)
          if (!attackerBot.isAlive) {
            try {
              const spawned = onceWithTimeout(attackerBot, 'spawn', 10000)
              attackerBot.respawn()
              await spawned
            } catch {}
          }
        }
      }
    }
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    report.confirmedAttempts = report.attempts.filter(row => row.duplicated).length
    report.exactPreservationAttempts = report.attempts.filter(row => row.preservedExactly).length
    report.totalAttempts = report.attempts.length
    report.confirmed = report.confirmedAttempts > 0
    fs.writeFileSync(path.join(OUTPUT_DIR, 'soulbound-dupe-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'soulbound-dupe-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab Soulbound complete') } catch {}
    }
  }

  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'soulbound-dupe-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
