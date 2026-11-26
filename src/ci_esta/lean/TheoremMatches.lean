import Lean

open Lean

/-- Normalize presentation without expanding Lean's shared expression DAG. -/
partial def normalize (expr : Expr) : StateM (Std.HashMap ExprStructEq Expr) Expr := do
  let key := ExprStructEq.mk expr
  if let some core := (← get)[key]? then return core
  let core ← match expr with
    | .forallE _ domain body info => return .forallE .anonymous (← normalize domain) (← normalize body) info
    | .lam _ domain body info => return .lam .anonymous (← normalize domain) (← normalize body) info
    | .letE _ type value body nonDep =>
      return .letE .anonymous (← normalize type) (← normalize value) (← normalize body) nonDep
    | .app fn arg => return .app (← normalize fn) (← normalize arg)
    | .mdata _ body => normalize body
    | .proj type index body => return .proj type index (← normalize body)
    | atom => pure atom
  modify (·.insert key core)
  return core

def statementCore (expr : Expr) : Expr := (normalize expr).run' {}

structure Candidate where
  owner : Name
  name : Name
  needsVerification : Bool

def eligible (name : Name) : Bool :=
  match name with
  | .str _ suffix =>
    !name.isInternalDetail && !["eq_def", "congr_simp"].contains suffix &&
      !suffix.startsWith "congr_eq_"
  | _ => false

/-- Public exports may represent both theorems and axioms as axioms. Verify
the original declaration kind only for signatures that have a match. -/
def verifyExports (path : System.FilePath) (wanted : Std.HashSet Name) : IO (Array Name) := do
  let parts ← readModuleDataParts
    #[path, OLeanLevel.server.adjustFileName path, OLeanLevel.private.adjustFileName path]
  return parts.flatMap fun (data, _) => data.constants.filterMap fun info =>
    match info with
    | .thmInfo theoremInfo => if wanted.contains theoremInfo.name then some theoremInfo.name else none
    | _ => none

def exactGroups (modules : Array Name) : IO (Array (Array (String × String))) := do
  -- Compacted regions stay mapped until exit because expression keys can
  -- retain references into them.
  let mut groups : Std.HashMap ExprStructEq (Array Candidate) := {}
  let mut seen : Std.HashSet Name := {}
  for owner in modules do
    let (data, _) ← readModuleData (← findOLean owner)
    for info in data.constants do
      let needsVerification ← match info with
        | .thmInfo _ => pure false
        | .axiomInfo _ => if data.isModule then pure true else continue
        | _ => continue
      let name := info.name
      if !eligible name || seen.contains name then continue
      seen := seen.insert name
      let levels := (List.range info.levelParams.length).map (fun i => Level.param (.num `u i))
      let core := statementCore (info.instantiateTypeLevelParams levels)
      let key := ExprStructEq.mk core
      groups := groups.alter key (fun group =>
        some ((group.getD #[]).push {owner, name, needsVerification}))
  let candidates := (groups.toArray.map Prod.snd).filter (·.size > 1)
  let mut verification : Std.HashMap Name (Std.HashSet Name) := {}
  for group in candidates do
    for candidate in group do
      if candidate.needsVerification then
        verification := verification.alter candidate.owner (fun names =>
          some ((names.getD {}).insert candidate.name))
  let mut verified : Std.HashSet Name := {}
  for (owner, wanted) in verification do
    for name in ← verifyExports (← findOLean owner) wanted do
      verified := verified.insert name
  return candidates.filterMap fun group =>
    let names : Array (String × String) := (group.filter fun c => !c.needsVerification || verified.contains c.name)
      |>.map fun c => (c.owner.toString, c.name.toString)
    if names.size < 2 then none else some (names.qsort (fun a b => a.2 < b.2))

def main (args : List String) : IO Unit := do
  if args.isEmpty then
    throw (IO.userError "Supply one or more built Lean modules")
  initSearchPath (← findSysroot)
  let modules := args.eraseDups.toArray.map String.toName
  let groups := (← exactGroups modules).qsort (fun a b => a[0]!.2 < b[0]!.2)
  IO.println (toJson (groups.map (·.map fun (owner, name) =>
    Json.mkObj [("module", toJson owner), ("theorem", toJson name)]))).compress
