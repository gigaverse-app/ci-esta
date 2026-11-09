# Git for Windows bin/git.exe and cmd/git.exe launch the native executable.
# CI creates thousands of tiny repositories; use the same installation directly
# without changing Git configuration, hooks, verification, or test coverage.
$ErrorActionPreference = 'Stop'
$resolved = (Get-Command git -CommandType Application | Select-Object -First 1).Source
$directory = Split-Path $resolved -Parent
if ((Split-Path $directory -Leaf) -notin @('bin', 'cmd')) {
    Write-Host "Keeping Git from $resolved (unrecognized installation layout)"
    return
}
# Ask this installation for its active prefix. Git 2.56 moved x64 from mingw64
# to ucrt64; ARM64 and 32-bit installations have other prefixes.
$execPath = & $resolved --exec-path
if ($LASTEXITCODE -ne 0) { throw 'Cannot discover the active Git installation' }
$prefix = Split-Path (Split-Path $execPath -Parent) -Parent
$native = [IO.Path]::GetFullPath((Join-Path $prefix 'bin/git.exe'))
$installationDirectory = Get-Item -LiteralPath (Split-Path $directory -Parent)
# Package managers can expose the installation through a junction such as Scoop's current.
$linkTarget = $installationDirectory.ResolveLinkTarget($true)
if ($linkTarget) { $installationDirectory = $linkTarget }
$installation = $installationDirectory.FullName + [IO.Path]::DirectorySeparatorChar
# GIT_EXEC_PATH can point outside this installation; never adopt another Git.
if (!$native.StartsWith($installation, [StringComparison]::OrdinalIgnoreCase) -or
    !(Test-Path -LiteralPath $native -PathType Leaf)) {
    Write-Host "Keeping Git from $resolved (no native executable beside launcher)"
    return
}
if ($native -eq $resolved) {
    Write-Host "Already using native Git from $resolved"
    return
}
$before = & $resolved --version
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify current Git version' }
$after = & $native --version
if ($LASTEXITCODE -ne 0 -or $before -ne $after) {
    throw 'Native Git does not match the existing Git installation'
}
$nativeDirectory = Split-Path $native -Parent
$env:PATH = "$nativeDirectory$([IO.Path]::PathSeparator)$env:PATH"
if ($env:GITHUB_PATH) {
    $nativeDirectory | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
}
Write-Host "Using $native ($after)"
