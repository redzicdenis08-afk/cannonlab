'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const RESET_X = -1.25
const BOAT_X = -0.80
const BORDER_TARGET = 0.20
const Y = 65
const Z = 0.50
const STEP = 0.25
const TICK_MS = 50
const COURSE_END = 239.999
const LONG_TARGET = 240.72
const LONG_WITNESS = new Vec3(244, 65, 0)

const DISMOUNT_GRAMMARS = [
  { name: 'shift_once', frames: [{ shift: true }, {}] },
  { name: 'shift_hold_2', frames: [{ shift: true }, { shift: true }, {}] },
  { name: 'shift_hold_5', frames: [{ shift: true }, { shift: true }, { shift: true }, { shift: true }, { shift: true }, {}] },
  { name: 'shift_jump_once', frames: [{ shift: true, jump: true }, {}] },
  { name: 'jump_once', frames: [{ jump: true }, {}] },
  { name: 'shift_forward', frames: [{ shift: true, forward: true }, { shift: true }, {}] },
  { name: 'shift_backward', frames: [{ shift: true, backward: true }, { shift: true }, {}] }
]

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

function onceWithTimeout (emitter, eventName, timeoutMs) {
  return new Promise(resolve => {
    let settled = false
    const timer = setTimeout(() => finish(null), timeoutMs)
    const handler = (...args) => finish(args)
    function finish (value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      emitter.removeListener(eventName, handler)
      resolve(value)
    }
    emitter.once(eventName, handler)
  })
}

function messageWithPrefix (bot, prefix, timeoutMs = 1800) {
  return new Promise(resolve => {
    let settled = false
    const timer = setTimeout(() => finish(null), timeoutMs)
    const handler = message => {
      const text = String(message)
      const index = text.indexOf(prefix)
      if (index >= 0) finish(text.slice(index))
    }
    function finish (value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      bot.removeListener('messagestr', handler)
      resolve(value)
    }
    bot.on('messagestr', handler)
  })
}

async function command (bot, text, delay = 100) {
  bot.chat(text)
  await sleep(delay)
}

async function serverSnapshot (bot) {
  const messagePromise = messageWithPrefix(bot, 'COURSE_SNAPSHOT ', 2200)
  bot.chat('/courselab snapshot')
  const line = await messagePromise
  if (!line) return { ok: false, line: null }
  const match = line.match(/player=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?) health=(-?\d+(?:\.\d+)?) fire=(-?\d+) vehicle=(none|-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?)/)
  if (!match) return { ok: false, line }
  return {
    ok: true,
    line,
    position: { x: Number(match[1]), y: Number(match[2]), z: Number(match[3]) },
    health: Number(match[4]),
    fire: Number(match[5]),
    vehicle: match[6]
  }
}

async function setup (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, '/claimlab zone 0 239.999')
  await command(bot, '/courselab build mixed', 2800)
}

async function reset (bot) {
  if (bot.vehicle) {
    const event = onceWithTimeout(bot, 'dismount', 1200)
    bot.chat('/ride @s dismount')
    await event
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 100)
  const position = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat(`/tp @s ${RESET_X} ${Y} ${Z}`)
  if (!await position) throw new Error('Reset teleport packet missing')
  await command(bot, '/claimlab reset', 50)
  await command(bot, '/courselab reset', 50)
  await command(bot, '/claimlab mode likely', 50)
  await command(bot, `/claimlab relation ${USERNAME} enemy`, 50)
}

async function mountBoat (bot) {
  bot.chat(`/summon minecraft:oak_boat ${BOAT_X} ${Y} ${Z} {Rotation:[-90f,0f]}`)
  await sleep(140)
  let mounted = onceWithTimeout(bot, 'mount', 1700)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  if (!bot.vehicle) {
    mounted = onceWithTimeout(bot, 'mount', 900)
    bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
    await mounted
  }
  await sleep(100)
  return bot.vehicle || null
}

function writeVehicleMove (bot, boat, x) {
  boat.position.set(x, Y, Z)
  bot.entity.position.set(x, Y, Z)
  bot._client.write('vehicle_move', { x, y: Y, z: Z, yaw: -90, pitch: 0, onGround: true })
}

async function crossBorderAndAck (bot, boat) {
  for (const x of [-0.55, -0.30, -0.05]) {
    writeVehicleMove(bot, boat, x)
    await sleep(TICK_MS)
  }
  const correctionPromise = onceWithTimeout(bot._client, 'position', 2200)
  writeVehicleMove(bot, boat, BORDER_TARGET)
  const correctionArgs = await correctionPromise
  await sleep(150)
  return {
    corrected: Boolean(correctionArgs),
    correction: correctionArgs ? correctionArgs[0] : null,
    stillMounted: Boolean(bot.vehicle),
    boatExists: Boolean(bot.entities[boat.id])
  }
}

async function burstTo (bot, boat, targetX, batchSize) {
  let x = BORDER_TARGET + STEP
  let packets = 0
  let ticks = 0
  const playerCorrections = []
  const vehicleCorrections = []
  const playerHandler = packet => playerCorrections.push(packet)
  const vehicleHandler = packet => vehicleCorrections.push(packet)
  bot._client.on('position', playerHandler)
  bot._client.on('vehicle_move', vehicleHandler)
  const started = process.hrtime.bigint()

  while (x < targetX - 1e-9 && bot.vehicle && bot.entities[boat.id]) {
    let sent = 0
    while (sent < batchSize && x < targetX - 1e-9 && bot.vehicle && bot.entities[boat.id]) {
      writeVehicleMove(bot, boat, x)
      x += STEP
      packets++
      sent++
    }
    ticks++
    await sleep(TICK_MS)
  }
  if (bot.vehicle && bot.entities[boat.id]) {
    writeVehicleMove(bot, boat, targetX)
    packets++
    await sleep(100)
  }

  bot._client.removeListener('position', playerHandler)
  bot._client.removeListener('vehicle_move', vehicleHandler)
  return {
    packets,
    ticks,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    playerCorrections: playerCorrections.length,
    vehicleCorrections: vehicleCorrections.length,
    stillMounted: Boolean(bot.vehicle),
    boatExists: Boolean(bot.entities[boat.id])
  }
}

async function attemptDismount (bot, grammar) {
  if (!bot.vehicle) return { success: false, reason: 'not_mounted' }
  const eventPromise = onceWithTimeout(bot, 'dismount', 1800)
  for (const inputs of grammar.frames) {
    bot._client.write('player_input', { inputs })
    await sleep(TICK_MS)
  }
  const args = await eventPromise
  await sleep(150)
  return {
    success: Boolean(args),
    stillMounted: Boolean(bot.vehicle),
    eventVehicleId: args?.[0]?.id ?? null
  }
}

async function openWitness (bot, position) {
  await command(bot, `/setblock ${position.x} ${position.y} ${position.z} minecraft:barrel[facing=west]`, 80)
  let block = bot.blockAt(position)
  for (let attempt = 0; attempt < 20 && (!block || block.name !== 'barrel'); attempt++) {
    await sleep(80)
    block = bot.blockAt(position)
  }
  if (!block || block.name !== 'barrel') return { opened: false, reason: 'missing' }
  const opened = onceWithTimeout(bot, 'windowOpen', 1500)
  try {
    await bot.lookAt(position.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  if (!await opened) return { opened: false, reason: 'no_window' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function runTrial (bot, plan, id) {
  await reset(bot)
  const boat = await mountBoat(bot)
  if (!boat) return { ...plan, id, mounted: false, verified: false }
  await command(bot, `/courselab start ratchet-${id}`, 60)
  const border = await crossBorderAndAck(bot, boat)
  const burst = await burstTo(bot, boat, plan.targetX, plan.batchSize)
  await sleep(300)
  const mountedSnapshot = await serverSnapshot(bot)
  const witnessPos = plan.targetX > 100 ? LONG_WITNESS : new Vec3(Math.floor(plan.targetX) + 3, 65, 0)
  const mountedWitness = await openWitness(bot, witnessPos)
  const dismount = await attemptDismount(bot, plan.grammar)
  const finalSnapshot = await serverSnapshot(bot)
  const finalWitness = await openWitness(bot, witnessPos)
  await command(bot, '/courselab stop', 50)

  const requiredX = plan.targetX > 100 ? COURSE_END + 0.50 : plan.targetX - 0.50
  const mountedBeyond = mountedSnapshot.ok && mountedSnapshot.position.x >= requiredX
  const finalBeyond = finalSnapshot.ok && finalSnapshot.position.x >= requiredX
  return {
    ...plan,
    grammar: plan.grammar.name,
    id,
    mounted: true,
    border,
    burst,
    mountedSnapshot,
    mountedWitness,
    dismount,
    finalSnapshot,
    finalWitness,
    mountedVerified: mountedBeyond && mountedWitness.opened,
    exitVerified: dismount.success && finalBeyond && finalWitness.opened,
    verified: mountedBeyond && mountedWitness.opened && dismount.success && finalBeyond && finalWitness.opened
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'ratchet-burst-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      count: results.length
    },
    results
  }, null, 2))
  const rows = ['id,target_x,batch,grammar,border_corrected,border_mounted,packets,ticks,burst_ms,player_corrections,vehicle_corrections,mounted_x,mounted_health,mounted_witness,dismount_success,still_mounted,final_x,final_health,final_witness,mounted_verified,exit_verified,verified']
  for (const r of results) {
    rows.push([
      r.id, r.targetX, r.batchSize, r.grammar,
      r.border?.corrected ?? '', r.border?.stillMounted ?? '',
      r.burst?.packets ?? '', r.burst?.ticks ?? '', r.burst ? r.burst.elapsedMs.toFixed(3) : '',
      r.burst?.playerCorrections ?? '', r.burst?.vehicleCorrections ?? '',
      r.mountedSnapshot?.position?.x?.toFixed(6) ?? '', r.mountedSnapshot?.health ?? '',
      r.mountedWitness?.opened ?? '', r.dismount?.success ?? '', r.dismount?.stillMounted ?? '',
      r.finalSnapshot?.position?.x?.toFixed(6) ?? '', r.finalSnapshot?.health ?? '',
      r.finalWitness?.opened ?? '', r.mountedVerified, r.exitVerified, r.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'ratchet-burst-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try { if (bot && bot._client && !bot._client.ended) bot.quit('Ratchet burst complete') } catch (_) {}
  await sleep(250)
  process.exit(code)
}

async function main () {
  const bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username: USERNAME,
    auth: 'offline',
    version: '1.21.11',
    physicsEnabled: false,
    hideErrors: false
  })
  bot.on('kicked', reason => console.error('[RatchetBurst kicked]', reason))
  bot.on('error', error => console.error('[RatchetBurst error]', error))
  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setup(bot)

    const plans = []
    for (const batchSize of [8, 10, 16, 20]) {
      for (const grammar of DISMOUNT_GRAMMARS) {
        plans.push({ targetX: 16.72, batchSize, grammar })
      }
    }

    const results = []
    for (let id = 0; id < plans.length; id++) {
      const result = await runTrial(bot, plans[id], id)
      results.push(result)
      writeReport(results, bot)
      console.log(`[RatchetBurst] ${id + 1}/${plans.length} batch=${result.batchSize}` +
        ` grammar=${result.grammar} mountedX=${result.mountedSnapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` mountedWitness=${result.mountedWitness?.opened ?? false}` +
        ` dismount=${result.dismount?.success ?? false} finalX=${result.finalSnapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` verified=${result.verified}`)
    }

    const successfulGrammars = results.filter(r => r.exitVerified)
    const best = successfulGrammars.sort((a, b) => b.batchSize - a.batchSize)[0]
    if (best) {
      const longPlan = { targetX: LONG_TARGET, batchSize: best.batchSize, grammar: DISMOUNT_GRAMMARS.find(g => g.name === best.grammar) }
      const longResult = await runTrial(bot, longPlan, results.length)
      results.push(longResult)
      writeReport(results, bot)
      console.log(`[RatchetBurst] LONG batch=${longResult.batchSize} grammar=${longResult.grammar}` +
        ` mountedX=${longResult.mountedSnapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` witness=${longResult.mountedWitness?.opened ?? false}` +
        ` dismount=${longResult.dismount?.success ?? false}` +
        ` finalX=${longResult.finalSnapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` VERIFIED=${longResult.verified}`)
    }

    console.log(`[RatchetBurst] completed=${results.length}` +
      ` mountedVerified=${results.filter(r => r.mountedVerified).length}` +
      ` exitVerified=${results.filter(r => r.exitVerified).length}` +
      ` fullyVerified=${results.filter(r => r.verified).length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[RatchetBurst fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
