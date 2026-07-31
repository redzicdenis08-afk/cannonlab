from pathlib import Path
import shutil, subprocess, zipfile, json, hashlib

root = Path(r"C:\business n8n")
template = root / "output/phaselab-proof-harness-7.0.1/manual-build"
proj = root / "output/phaselab-purple-handoff-8.0/client"
manual = proj / "manual-build"
if manual.exists():
    shutil.rmtree(manual)
manual.mkdir(parents=True)
for name in ["mappings.tiny", "VerifyJar.java", "VerifyMixinTargets.java"]:
    shutil.copy2(template / name, manual / name)

old_root = "C:/business n8n/output/phaselab-proof-harness-7.0.1"
new_root = "C:/business n8n/output/phaselab-purple-handoff-8.0/client"

javac_text = (template / "javac.args").read_text(encoding="utf-8")
javac_text = javac_text.replace(old_root, new_root)
# Replace the template source tail with the two active sources.
lines = javac_text.splitlines()
lines = [line for line in lines if not (
    "src/client/java/dev/denis/phaselab/BoatPhaseClient.java" in line
    or "src/client/java/dev/denis/phaselab/ClientOnlyTargetGuard.java" in line
    or "src/client/java/dev/denis/phaselab/mixin/ClientPacketListenerMixin.java" in line
)]
lines.extend([
    '"C:/business n8n/output/phaselab-purple-handoff-8.0/client/src/client/java/dev/denis/phaselab/PurpleHandoffClient.java"',
    '"C:/business n8n/output/phaselab-purple-handoff-8.0/client/src/client/java/dev/denis/phaselab/mixin/ClientPacketListenerMixin.java"'
])
(manual / "javac.args").write_text("\n".join(lines) + "\n", encoding="utf-8")

remap_text = (template / "remap-min.args").read_text(encoding="utf-8")
remap_text = remap_text.replace(old_root, new_root)
remap_text = remap_text.replace("phaselab-proof-harness-7.0.1", "phaselab-purple-handoff-8.0.0")
(manual / "remap-min.args").write_text(remap_text, encoding="utf-8")

java = root / "LOCAL_TOOLS/cannonlab-build/jdk25/bin/java.exe"
javac = root / "LOCAL_TOOLS/cannonlab-build/jdk25/bin/javac.exe"
classes = manual / "classes"
classes.mkdir()
cp = subprocess.run([str(javac), "@" + str(manual / "javac.args")], cwd=root, capture_output=True, text=True, timeout=180)
print(json.dumps({"javac_exit": cp.returncode, "javac_err": cp.stderr[-4000:]}, indent=2))
if cp.returncode != 0:
    raise SystemExit(1)

named = manual / "phaselab-purple-handoff-8.0.0-named.jar"
with zipfile.ZipFile(named, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    for f in classes.rglob("*.class"):
        z.write(f, f.relative_to(classes).as_posix())
    res = proj / "src/client/resources"
    for f in res.rglob("*"):
        if not f.is_file():
            continue
        if f.name == "fabric.mod.json":
            data = f.read_text(encoding="utf-8").replace("${version}", "8.0.0-purple-handoff")
            z.writestr(f.relative_to(res).as_posix(), data)
        else:
            z.write(f, f.relative_to(res).as_posix())

rm = subprocess.run([str(java), "@" + str(manual / "remap-min.args")], cwd=root, capture_output=True, text=True, timeout=180)
final = manual / "phaselab-purple-handoff-8.0.0.jar"
print(json.dumps({"remap_exit": rm.returncode, "remap_err": rm.stderr[-4000:], "final_exists": final.exists(), "final_bytes": final.stat().st_size if final.exists() else None}, indent=2))
if rm.returncode != 0 or not final.exists():
    raise SystemExit(2)
print("sha256=" + hashlib.sha256(final.read_bytes()).hexdigest())
