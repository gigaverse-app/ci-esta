import Lean

open Lean Lean.Elab

def importsOf (path : String) : IO Json := do
  let source ← IO.FS.readFile path
  let (imports, _, messages) ← parseImports source (some path)
  if messages.hasErrors then
    throw (IO.userError s!"Lean could not parse the import header in {path}")
  return toJson (imports.map (·.module.toString))

def main (paths : List String) : IO Unit := do
  for path in paths do
    IO.println (← importsOf path).compress
