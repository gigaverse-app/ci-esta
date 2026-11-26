module

public import Init

@[expose] public section

universe u v

theorem left (α : Type u) (value : α) : value = value := rfl
theorem right (β : Type v) (input : β) : input = input := by rfl
theorem different (α : Type u) (a b : α) : a = b → b = a := Eq.symm
theorem implicit {α : Type u} (value : α) : value = value := rfl
axiom exactSignatureAxiom (α : Type u) (value : α) : value = value
