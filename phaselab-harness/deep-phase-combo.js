'use strict'
/**
 * deep-phase-combo.js  —  Novel phase vector research, PhaseLab 2026-07-29
 *
 * Three untested attack vectors on bare Sakura 26.1.2 (no defense plugins):
 *
 *   MODULE A  mounted_pearl
 *     Mount oak boat → throw pearl at confirmed pitch-89 angles → check if
 *     dismount+teleport race puts player inside obsidian wall
 *
 *   MODULE B  z_fraction_sweep
 *     Exhaustive sub-block Z search (11 positions vs original 2) at confirmed
 *     pitch=89 angles. Finds which Z positions have highest overlap rate.
 *     A real raider only needs the best 1-2 positions.
 *
 *   MODULE C  vehicle_move_escape
 *     Pearl overlap teleport → summon + mount boat inside wall → escape via
 *     vehicle_move packets (different server handler than player position,
 *     may bypass post-teleport correction logic)
 */

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const Y = 65
const ORIGIN_X = 0.69
const WALL_MIN_X = 1.0
const WALL_MAX_X = 2.0
const TARGET_X = 2.35
const WITNESS = new Vec3(5, Y, 0)

// Confirmed working parameters from pearl-overlap-escape run (17/116 verified)
const PITCHES = [89]
const YAWS = [-85, -90, -95]
const ESCAPE_STEPS = [0.05, 0.249]
const REPEATS = 2

// MODULE B: Z fractions — original only tested 0.241 and 0.759
const Z_FRACTIONS = [0.10, 0.20, 0.241, 0.30, 0.40, 0.50, 0.60, 0.70, 0.759, 0.80, 0.90]

const sleep = ms => new Promise(r => setTimeout(r, ms))
fs.mkdirSync(OUTPUT_DIR, { recursive: true })

function onceWithTimeout (emitter, event, ms) {
  return new Promise(resolve => {
    let done = false
    const timer = setTimeout(() => finish(null), ms)
    const handler = (...args) => finish(args)
    function finish (v) {
      if (done) return
      done = true
      clearTimeout(timer)
      emitter.removeListener(event, handler)
      resolve(v)
    }
    emitter.once(event, handler)
  })
}

async function cmd (bot, text, delay = 150) {
  bot.chat(text)
  await sleep(delay)
}

async function setupArena (bot) {
  await cmd(bot, '/gamerule doDaylightCycle false')
  await cmd(bot, '/time set day')
  await cmd(bot, `/gamemode survival ${USERNAME}`)
  await cmd(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await cmd(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await cmd(bot, '/fill -4 63 -4 8 72 4 minecraft:air', 250)
  await cmd(bot, '/fill -4 64 -4 8 64 4 minecraft:stone', 180)
  await cmd(bot, '/fill 1 65 -1 1 68 1 minecraft:obsidian', 120)
  await cmd(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 100)
  await sleep(300)
}

async function resetPlayer (bot, x, z) {
  const posPromise = onceWithTimeout(bot._client, 'position', 3500)
  bot.chat(`/tp ${USERNAME} ${x} ${Y} ${z} -90 89`)
  if (!await posPromise) throw new Error(`Reset tp packet missing at x=${x} z=${z}`)
  await sleep(180)
  bot.entity.velocity = new Vec3(0, 0, 0)
}

async function ensurePearl (bot) {
  let pearl = bot.inventory.items().find(i => i.name === 'ender_pearl')
  if (!pearl) {
    await cmd(bot, `/give ${USERNAME} minecraft:ender_pearl 64`, 400)
    pearl = bot.inventory.items().find(i => i.name === 'ender_pearl')
  }
  if (!pearl) throw new Error('No ender pearl available')
  await bot.equip(pearl, 'hand')
  await sleep(80)
}

function overlapsWall (pos) {
  const hw = 0.30
  return pos.x + hw > WALL_MIN_X && pos.x - hw < WALL_MAX_X
}

function packetPos (p) {
  return {
    x: Number.isFinite(p.x) ? p.x : null,
    y: Number.isFinite(p.y) ? p.y : null,
    z: Number.isFinite(p.z) ? p.z : null
  }
}

async function doPositionEscape (bot, startPos, step, corrections) {
  let x = startPos.x + step
  let pkts = 0
  while (x < TARGET_X - 1e-9 && corrections.length === 0) {
    bot._client.write('position', {
      x, y: startPos.y, z: startPos.z,
      flags: { onGround: false, hasHorizontalCollision: true }
    })
    bot.entity.position.set(x, startPos.y, startPos.z)
    pkts++
    await sleep(50)
    x += step
  }
  if (corrections.length === 0) {
    bot._client.write('position', {
      x: TARGET_X, y: startPos.y, z: startPos.z,
      flags: { onGround: false, hasHorizontalCollision: true }
    })
    pkts++
  }
  return pkts
}

async function authSnapshot (bot) {
  const p = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat('/tp @s ~ ~ ~')
  await p
  await sleep(100)
  return { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
}

async function tryWitness (bot) {
  await cmd(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 80)
  let block = bot.blockAt(WITNESS)
  for (let i = 0; i < 12 && (!block || block.name !== 'barrel'); i++) {
    await sleep(80)
    block = bot.blockAt(WITNESS)
  }
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  }
  const opened = onceWithTimeout(bot, 'windowOpen', 1400)
  try {
    await bot.lookAt(WITNESS.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (e) {
    return { opened: false, reason: `activate:${e.message}` }
  }
  if (!await opened) return { opened: false, reason: 'no_window' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

// ── MODULE A: Mounted Pearl ─────────────────────────────────────────────────
// Throw pearl while sitting in a boat. The server must dismount before teleporting.
// If the dismount+teleport ordering has a race, player may land inside wall
// while vehicle state is still active (compound with STRICT mode blind window).

async function runModuleA (bot, plan, id) {
  await cmd(bot, '/kill @e[type=minecraft:oak_boat]', 100)
  await resetPlayer(bot, ORIGIN_X, plan.z)
  await ensurePearl(bot)

  // Summon and mount boat
  bot.chat(`/summon minecraft:oak_boat ${ORIGIN_X} ${Y} ${plan.z} {Rotation:[-90f,0f],Invulnerable:1b}`)
  await sleep(150)
  const mountedEvt = onceWithTimeout(bot, 'mount', 1800)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  const mountResult = await mountedEvt
  const wasMounted = Boolean(mountResult)
  await sleep(100)

  await bot.look(plan.yaw * Math.PI / 180, plan.pitch * Math.PI / 180, true)
  await sleep(100)

  const t0 = Date.now()
  const teleportPromise = onceWithTimeout(bot._client, 'position', 7000)
  bot.activateItem()
  const teleportArgs = await teleportPromise
  const pearlMs = Date.now() - t0
  await sleep(150)

  if (!teleportArgs) {
    await cmd(bot, '/kill @e[type=minecraft:oak_boat]', 80)
    await sleep(500)
    return { module: 'A', id, plan, wasMounted, pearlMs, pearlPos: null, overlap: false, escapePackets: 0, corrections: 0, snapPos: null, witness: { opened: false, reason: 'no_teleport' }, verified: false }
  }

  const pearlPos = { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
  const overlap = overlapsWall(pearlPos)
  const corrections = []
  const ct0 = process.hrtime.bigint()
  const corrHandler = p => corrections.push({ ms: Number(process.hrtime.bigint() - ct0) / 1e6, pos: packetPos(p) })
  bot._client.on('position', corrHandler)

  let escapePkts = 0
  if (overlap) {
    escapePkts = await doPositionEscape(bot, pearlPos, plan.escapeStep, corrections)
    await sleep(500)
  }
  bot._client.removeListener('position', corrHandler)

  await cmd(bot, '/kill @e[type=minecraft:oak_boat]', 80)
  if (bot.vehicle) {
    const dis = onceWithTimeout(bot, 'dismount', 1000)
    bot.dismount()
    await dis
    await sleep(120)
  }

  const snapPos = await authSnapshot(bot)
  const beyond = snapPos.x >= TARGET_X - 0.05
  const witness = (beyond && corrections.length === 0)
    ? await tryWitness(bot)
    : { opened: false, reason: overlap ? (corrections.length ? 'corrected' : 'not_beyond') : 'no_overlap' }
  await sleep(600)

  return {
    module: 'A', id, plan, wasMounted, pearlMs,
    pearlPos, overlap, escapePackets: escapePkts,
    corrections: corrections.length, snapPos, beyond, witness,
    verified: overlap && corrections.length === 0 && beyond && witness.opened
  }
}

// ── MODULE B: Z Fraction Sweep ──────────────────────────────────────────────
// Original pearl-overlap-escape.js only tested Z=0.241 and Z=0.759.
// Z=0.759 had 0 verified. Z=0.241 had 17 verified (pitch=89 only).
// Sweep 11 Z values to find the sweet spot for a real raider.

async function runModuleB (bot, plan, id) {
  await resetPlayer(bot, ORIGIN_X, plan.z)
  await ensurePearl(bot)
  await bot.look(plan.yaw * Math.PI / 180, plan.pitch * Math.PI / 180, true)
  await sleep(100)

  const t0 = Date.now()
  const teleportPromise = onceWithTimeout(bot._client, 'position', 7000)
  bot.activateItem()
  const teleportArgs = await teleportPromise
  const pearlMs = Date.now() - t0

  if (!teleportArgs) {
    await sleep(800)
    return { module: 'B', id, plan, pearlMs, pearlPos: null, overlap: false, escapePackets: 0, corrections: 0, snapPos: null, witness: { opened: false, reason: 'no_teleport' }, verified: false }
  }

  const pearlPos = { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
  const overlap = overlapsWall(pearlPos)
  const corrections = []
  const ct0 = process.hrtime.bigint()
  const corrHandler = p => corrections.push({ ms: Number(process.hrtime.bigint() - ct0) / 1e6, pos: packetPos(p) })
  bot._client.on('position', corrHandler)

  let escapePkts = 0
  if (overlap) {
    escapePkts = await doPositionEscape(bot, pearlPos, plan.escapeStep, corrections)
    await sleep(500)
  }
  bot._client.removeListener('position', corrHandler)

  const snapPos = await authSnapshot(bot)
  const beyond = snapPos.x >= TARGET_X - 0.05
  const witness = (beyond && corrections.length === 0)
    ? await tryWitness(bot)
    : { opened: false, reason: overlap ? (corrections.length ? 'corrected' : 'not_beyond') : 'no_overlap' }
  await sleep(600)

  return {
    module: 'B', id, plan, pearlMs,
    pearlPos, overlap, escapePackets: escapePkts,
    corrections: corrections.length, snapPos, beyond, witness,
    verified: overlap && corrections.length === 0 && beyond && witness.opened
  }
}

// ── MODULE C: Vehicle Move Escape ───────────────────────────────────────────
// After pearl teleports player into overlapping wall position, summon a boat
// on the player and /ride into it. Then send vehicle_move packets to escape.
// vehicle_move goes through server handleVehicleMove(), not handleMovePlayer().
// If Sakura's movement guards only hook handleMovePlayer, this bypasses them.

async function doVehicleMoveEscape (bot, startPos, step, corrections) {
  bot.chat(`/summon minecraft:oak_boat ${startPos.x.toFixed(4)} ${(startPos.y - 0.5).toFixed(4)} ${startPos.z.toFixed(4)} {Rotation:[-90f,0f],Invulnerable:1b}`)
  await sleep(200)
  const mountEvt = onceWithTimeout(bot, 'mount', 1600)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  const mountResult = await mountEvt
  if (!mountResult) return { pkts: 0, mounted: false }

  await sleep(80)
  let x = startPos.x + step
  let pkts = 0
  // vehicle_move: x/y/z are root vehicle position, yaw/pitch are vehicle rotation
  while (x < TARGET_X - 1e-9 && corrections.length === 0) {
    bot._client.write('vehicle_move', {
      x,
      y: startPos.y - 0.5,
      z: startPos.z,
      yaw: -90,
      pitch: 0
    })
    pkts++
    await sleep(50)
    x += step
  }
  if (corrections.length === 0) {
    bot._client.write('vehicle_move', {
      x: TARGET_X,
      y: startPos.y - 0.5,
      z: startPos.z,
      yaw: -90,
      pitch: 0
    })
    pkts++
  }
  return { pkts, mounted: true }
}

async function runModuleC (bot, plan, id) {
  await cmd(bot, '/kill @e[type=minecraft:oak_boat]', 80)
  await resetPlayer(bot, ORIGIN_X, plan.z)
  await ensurePearl(bot)
  await bot.look(plan.yaw * Math.PI / 180, plan.pitch * Math.PI / 180, true)
  await sleep(100)

  const t0 = Date.now()
  const teleportPromise = onceWithTimeout(bot._client, 'position', 7000)
  bot.activateItem()
  const teleportArgs = await teleportPromise
  const pearlMs = Date.now() - t0

  if (!teleportArgs) {
    return { module: 'C', id, plan, pearlMs, pearlPos: null, overlap: false, vehicleMounted: false, escapePackets: 0, corrections: 0, snapPos: null, witness: { opened: false, reason: 'no_teleport' }, verified: false }
  }

  const pearlPos = { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
  const overlap = overlapsWall(pearlPos)
  const corrections = []
  const ct0 = process.hrtime.bigint()
  const corrHandler = p => corrections.push({ ms: Number(process.hrtime.bigint() - ct0) / 1e6, pos: packetPos(p) })
  bot._client.on('position', corrHandler)

  let vehicleMounted = false
  let escapePkts = 0
  if (overlap) {
    const escapeResult = await doVehicleMoveEscape(bot, pearlPos, plan.escapeStep, corrections)
    vehicleMounted = escapeResult.mounted
    escapePkts = escapeResult.pkts
    await sleep(500)
  }
  bot._client.removeListener('position', corrHandler)

  // Dismount before snapshot
  if (bot.vehicle) {
    const dis = onceWithTimeout(bot, 'dismount', 1200)
    bot.dismount()
    await dis
    await sleep(150)
  }
  await cmd(bot, '/kill @e[type=minecraft:oak_boat]', 80)

  const snapPos = await authSnapshot(bot)
  const beyond = snapPos.x >= TARGET_X - 0.05
  const witness = (beyond && corrections.length === 0)
    ? await tryWitness(bot)
    : { opened: false, reason: overlap ? (corrections.length ? 'corrected' : 'not_beyond') : 'no_overlap' }
  await sleep(600)

  return {
    module: 'C', id, plan, pearlMs,
    pearlPos, overlap, vehicleMounted, escapePackets: escapePkts,
    corrections: corrections.length, snapPos, beyond, witness,
    verified: overlap && corrections.length === 0 && beyond && witness.opened
  }
}

// ── Report ──────────────────────────────────────────────────────────────────

function writeReports (results) {
  fs.writeFileSync(
    path.join(OUTPUT_DIR, 'deep-phase-combo.json'),
    JSON.stringify({ generatedAt: new Date().toISOString(), count: results.length, results }, null, 2)
  )
  const rows = ['module,id,z,pitch,yaw,escape_step,pearl_ms,pearl_x,pearl_y,overlap,escape_pkts,corrections,snap_x,beyond,witness,verified']
  for (const r of results) {
    rows.push([
      r.module, r.id,
      r.plan.z, r.plan.pitch, r.plan.yaw, r.plan.escapeStep,
      r.pearlMs != null ? r.pearlMs.toFixed(0) : '',
      r.pearlPos != null ? r.pearlPos.x.toFixed(4) : '',
      r.pearlPos != null ? r.pearlPos.y.toFixed(4) : '',
      r.overlap,
      r.escapePackets,
      r.corrections,
      r.snapPos != null ? r.snapPos.x.toFixed(4) : '',
      r.beyond,
      r.witness ? r.witness.opened : '',
      r.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'deep-phase-combo.csv'), rows.join('\n') + '\n')
}

// ── Main ────────────────────────────────────────────────────────────────────

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab deep combo complete')
  } catch (_) {}
  await sleep(300)
  process.exit(code)
}

async function main () {
  const bot = mineflayer.createBot({
    host: HOST, port: PORT, username: USERNAME,
    auth: 'offline', version: '1.21.11',
    physicsEnabled: false, hideErrors: false
  })
  bot.on('kicked', r => console.error('[DeepCombo kicked]', r))
  bot.on('error', e => console.error('[DeepCombo error]', e))

  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn within 30s')
    bot.physicsEnabled = false
    await sleep(900)
    await setupArena(bot)

    const results = []
    let id = 0

    // MODULE A: Mounted Pearl
    console.log('[DeepCombo] ===== MODULE A: Mounted Pearl =====')
    for (const pitch of PITCHES) {
      for (const yaw of YAWS) {
        for (const escapeStep of ESCAPE_STEPS) {
          for (let rep = 0; rep < REPEATS; rep++) {
            const plan = { z: 0.241, pitch, yaw, escapeStep }
            const r = await runModuleA(bot, plan, id++)
            results.push(r)
            writeReports(results)
            console.log(`[A] yaw=${yaw} step=${escapeStep} rep=${rep} mounted=${r.wasMounted} overlap=${r.overlap} corrections=${r.corrections} beyond=${r.beyond} verified=${r.verified}`)
          }
        }
      }
    }

    // MODULE B: Z Fraction Sweep
    console.log('[DeepCombo] ===== MODULE B: Z Fraction Sweep =====')
    for (const z of Z_FRACTIONS) {
      for (const pitch of PITCHES) {
        for (const yaw of YAWS) {
          for (const escapeStep of ESCAPE_STEPS) {
            for (let rep = 0; rep < REPEATS; rep++) {
              const plan = { z, pitch, yaw, escapeStep }
              const r = await runModuleB(bot, plan, id++)
              results.push(r)
              writeReports(results)
              console.log(`[B] z=${z} yaw=${yaw} step=${escapeStep} rep=${rep} overlap=${r.overlap} corrections=${r.corrections} verified=${r.verified}`)
            }
          }
        }
      }
    }

    // MODULE C: Vehicle Move Escape
    console.log('[DeepCombo] ===== MODULE C: Vehicle Move Escape =====')
    for (const pitch of PITCHES) {
      for (const yaw of YAWS) {
        for (const escapeStep of ESCAPE_STEPS) {
          for (let rep = 0; rep < REPEATS; rep++) {
            const plan = { z: 0.241, pitch, yaw, escapeStep }
            const r = await runModuleC(bot, plan, id++)
            results.push(r)
            writeReports(results)
            console.log(`[C] yaw=${yaw} step=${escapeStep} rep=${rep} overlap=${r.overlap} vehicleMounted=${r.vehicleMounted} corrections=${r.corrections} verified=${r.verified}`)
          }
        }
      }
    }

    const verified = results.filter(r => r.verified)
    const aV = verified.filter(r => r.module === 'A').length
    const bV = verified.filter(r => r.module === 'B').length
    const cV = verified.filter(r => r.module === 'C').length
    console.log(`[DeepCombo] COMPLETE: ${results.length} trials total, ${verified.length} verified phases`)
    console.log(`[DeepCombo] A(mounted_pearl)=${aV}  B(z_sweep)=${bV}  C(vehicle_move_escape)=${cV}`)
    if (bV > 0) {
      const bVerified = verified.filter(r => r.module === 'B')
      const zCounts = {}
      for (const r of bVerified) {
        zCounts[r.plan.z] = (zCounts[r.plan.z] || 0) + 1
      }
      console.log('[DeepCombo] B best Z positions:', JSON.stringify(zCounts))
    }
    await shutdown(bot, 0)
  } catch (e) {
    console.error('[DeepCombo fatal]', e)
    await shutdown(bot, 1)
  }
}

main()
