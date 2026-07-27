'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
fs.mkdirSync(OUTPUT_DIR, { recursive: true })

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

function waitForText (bot, needle, timeoutMs = 1800) {
  return new Promise(resolve => {
    let settled = false
    const timer = setTimeout(() => finish(null), timeoutMs)
    const handler = message => {
      const text = String(message)
      if (text.includes(needle)) finish(text)
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

async function serverMountStatus (bot) {
  const messagePromise = waitForText(bot, 'InputProbe active=', 2000)
  bot.chat('/inputlab status')
  const line = await messagePromise
  const vehicle = line?.match(/vehicle=([^ ]+)/)?.[1] ?? null
  return {
    line,
    vehicle,
    mounted: Boolean(vehicle && vehicle !== 'none')
  }
}

async function forceCleanState (bot) {
  bot.chat('/ride @s dismount')
  await sleep(250)
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 150)
  bot.vehicle = null
  const positionPromise = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat('/tp @s 0.5 65 0.5')
  if (!await positionPromise) throw new Error('Reset position packet missing')
  await sleep(120)
}

function nearestBoat (bot) {
  return Object.values(bot.entities)
    .filter(entity => entity.name === 'oak_boat' || entity.displayName === 'Boat' || entity.objectType === 'Boat')
    .sort((a, b) => a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position))[0] || null
}

async function summonAndMount (bot, preferNormal) {
  await forceCleanState(bot)
  bot.chat('/summon minecraft:oak_boat 0.5 65 0.5 {Rotation:[0f,0f],Invulnerable:1b}')
  await sleep(350)

  let method = 'command'
  let boat = nearestBoat(bot)
  if (preferNormal && boat) {
    const mountPromise = onceWithTimeout(bot, 'mount', 1800)
    try {
      bot.mount(boat)
    } catch (_) {}
    await mountPromise
    await sleep(250)
    const normalStatus = await serverMountStatus(bot)
    if (normalStatus.mounted) method = 'normal'
  }

  let status = await serverMountStatus(bot)
  if (!status.mounted) {
    const mountPromise = onceWithTimeout(bot, 'mount', 1800)
    bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
    await mountPromise
    await sleep(250)
    status = await serverMountStatus(bot)
  }

  boat = nearestBoat(bot)
  return {
    method,
    serverMounted: status.mounted,
    serverVehicle: status.vehicle,
    clientMounted: Boolean(bot.vehicle),
    clientVehicleId: bot.vehicle?.id ?? null,
    boatId: boat?.id ?? null,
    statusLine: status.line
  }
}

async function sendFrames (bot, frames, { tickEnd = false, frameMs = 50 } = {}) {
  for (const inputs of frames) {
    bot._client.write('player_input', { inputs })
    if (tickEnd) bot._client.write('tick_end', {})
    await sleep(frameMs)
  }
}

async function runSequence (bot, plan, id) {
  const mount = await summonAndMount(bot, plan.normalMount)
  await command(bot, `/inputlab start ${id}-${plan.name}`, 100)
  const dismountPromise = onceWithTimeout(bot, 'dismount', 2400)
  let error = null

  try {
    if (plan.kind === 'raw') {
      await sendFrames(bot, plan.frames, { tickEnd: plan.tickEnd, frameMs: plan.frameMs || 50 })
    } else if (plan.kind === 'helper') {
      bot.dismount()
      if (plan.tickEnd) bot._client.write('tick_end', {})
    } else if (plan.kind === 'control') {
      bot.physicsEnabled = true
      bot.setControlState('sneak', true)
      for (let elapsed = 0; elapsed < plan.holdMs; elapsed += 50) {
        if (plan.tickEnd) bot._client.write('tick_end', {})
        await sleep(50)
      }
      bot.setControlState('sneak', false)
      bot._client.write('player_input', { inputs: {} })
      if (plan.tickEnd) bot._client.write('tick_end', {})
      await sleep(120)
      bot.physicsEnabled = false
    }
  } catch (caught) {
    error = caught.message
    bot.physicsEnabled = false
  }

  const dismountArgs = await dismountPromise
  await sleep(250)
  const serverAfter = await serverMountStatus(bot)
  await command(bot, '/inputlab stop', 60)

  return {
    id,
    name: plan.name,
    kind: plan.kind,
    tickEnd: Boolean(plan.tickEnd),
    normalMount: Boolean(plan.normalMount),
    mount,
    error,
    dismountEvent: Boolean(dismountArgs),
    serverStillMounted: serverAfter.mounted,
    serverVehicleAfter: serverAfter.vehicle,
    clientStillMounted: Boolean(bot.vehicle),
    position: {
      x: bot.entity.position.x,
      y: bot.entity.position.y,
      z: bot.entity.position.z
    }
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'input-dismount-v2-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['id,name,kind,tick_end,normal_mount,mount_method,server_mounted_before,server_vehicle_before,client_mounted_before,error,dismount_event,server_still_mounted,server_vehicle_after,client_still_mounted,x,y,z']
  for (const result of results) {
    rows.push([
      result.id,
      result.name,
      result.kind,
      result.tickEnd,
      result.normalMount,
      result.mount.method,
      result.mount.serverMounted,
      result.mount.serverVehicle || '',
      result.mount.clientMounted,
      result.error || '',
      result.dismountEvent,
      result.serverStillMounted,
      result.serverVehicleAfter || '',
      result.clientStillMounted,
      result.position.x.toFixed(6),
      result.position.y.toFixed(6),
      result.position.z.toFixed(6)
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'input-dismount-v2-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('Input probe v2 complete')
  } catch (_) {}
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
  bot.on('kicked', reason => console.error('[InputProbeV2 kicked]', reason))
  bot.on('error', error => console.error('[InputProbeV2 error]', error))

  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(850)
    await command(bot, `/gamemode survival ${USERNAME}`)
    await command(bot, '/fill -5 64 -5 5 64 5 minecraft:stone')
    await command(bot, '/fill -5 65 -5 5 70 5 minecraft:air')

    const shift20 = Array.from({ length: 20 }, () => ({ shift: true })).concat([{}])
    const jump20 = Array.from({ length: 20 }, () => ({ jump: true })).concat([{}])
    const both20 = Array.from({ length: 20 }, () => ({ shift: true, jump: true })).concat([{}])
    const plans = [
      { name: 'shift20_no_tick_end_command', kind: 'raw', frames: shift20, tickEnd: false, normalMount: false },
      { name: 'shift20_tick_end_command', kind: 'raw', frames: shift20, tickEnd: true, normalMount: false },
      { name: 'jump20_tick_end_command', kind: 'raw', frames: jump20, tickEnd: true, normalMount: false },
      { name: 'shift_jump20_tick_end_command', kind: 'raw', frames: both20, tickEnd: true, normalMount: false },
      { name: 'helper_tick_end_command', kind: 'helper', tickEnd: true, normalMount: false },
      { name: 'control_sneak_tick_end_command', kind: 'control', holdMs: 1000, tickEnd: true, normalMount: false },
      { name: 'shift20_tick_end_normal', kind: 'raw', frames: shift20, tickEnd: true, normalMount: true },
      { name: 'control_sneak_tick_end_normal', kind: 'control', holdMs: 1000, tickEnd: true, normalMount: true }
    ]

    const results = []
    for (let id = 0; id < plans.length; id++) {
      const result = await runSequence(bot, plans[id], id)
      results.push(result)
      writeReport(results, bot)
      console.log(`[InputProbeV2] ${result.name}` +
        ` serverBefore=${result.mount.serverMounted}` +
        ` mount=${result.mount.method}` +
        ` dismountEvent=${result.dismountEvent}` +
        ` serverAfter=${result.serverStillMounted}` +
        ` clientAfter=${result.clientStillMounted}` +
        ` error=${result.error || 'none'}`)
    }

    console.log(`[InputProbeV2] completed=${results.length}` +
      ` serverDismounted=${results.filter(result => !result.serverStillMounted).length}` +
      ` dismountEvents=${results.filter(result => result.dismountEvent).length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[InputProbeV2 fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
