$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$jdk = 'C:/business n8n/LOCAL_TOOLS/cannonlab-build/jdk25/bin'
$manual = Join-Path $root 'build/manual'
$log = Join-Path $root 'build-manual.log'
$exitFile = Join-Path $root 'build-manual.exit'
Remove-Item $log,$exitFile -Force -ErrorAction SilentlyContinue
try {
  Remove-Item "$manual/classes","$manual/resources","$manual/testclasses" -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path "$manual/classes","$manual/resources","$manual/testclasses","$root/build/libs" | Out-Null
  $jars = Get-ChildItem 'C:/Users/dess/.gradle/caches/modules-2/files-2.1' -Recurse -Filter '*.jar' -File | ForEach-Object { $_.FullName.Replace('\','/') }
  $cp = $jars -join ';'
  $sources = Get-ChildItem "$root/src/main/java" -Recurse -Filter '*.java' -File | ForEach-Object { $_.FullName.Replace('\','/') }
  $out = (Join-Path $manual 'classes').Replace('\','/')
  $args = @('--release','25','-encoding','UTF-8','-classpath',('"'+$cp+'"'),'-d',('"'+$out+'"')) + ($sources | ForEach-Object {'"'+$_+'"'})
  Set-Content "$manual/javac.args" $args -Encoding ascii
  & "$jdk/javac.exe" "@$manual/javac.args" *> $log
  if ($LASTEXITCODE -ne 0) { throw "javac failed with $LASTEXITCODE" }
  (Get-Content "$root/src/main/resources/plugin.yml" -Raw).Replace('${version}','1.0.0') | Set-Content "$manual/resources/plugin.yml" -Encoding utf8
  & "$jdk/jar.exe" --create --file "$root/build/libs/PhaseLab-SetbackProfiler-1.0.0.jar" -C "$manual/classes" . -C "$manual/resources" . *>> $log
  if ($LASTEXITCODE -ne 0) { throw "jar failed with $LASTEXITCODE" }
  $testSource = (Join-Path $manual 'testsrc/dev/denis/phaselab/profiler/SetbackClassifierSelfTest.java').Replace('\','/')
  $testOut = (Join-Path $manual 'testclasses').Replace('\','/')
  $testArgs = @('--release','25','-encoding','UTF-8','-classpath',('"'+$out+'"'),'-d',('"'+$testOut+'"'),('"'+$testSource+'"'))
  Set-Content "$manual/test-javac.args" $testArgs -Encoding ascii
  & "$jdk/javac.exe" "@$manual/test-javac.args" *>> $log
  if ($LASTEXITCODE -ne 0) { throw "test javac failed with $LASTEXITCODE" }
  $testCp = ((Join-Path $manual 'classes') + ';' + (Join-Path $manual 'testclasses'))
  & "$jdk/java.exe" -cp $testCp dev.denis.phaselab.profiler.SetbackClassifierSelfTest *>> $log
  if ($LASTEXITCODE -ne 0) { throw "self test failed with $LASTEXITCODE" }
  '0' | Set-Content $exitFile -Encoding ascii
} catch {
  $_ | Out-String | Add-Content $log
  '1' | Set-Content $exitFile -Encoding ascii
}
