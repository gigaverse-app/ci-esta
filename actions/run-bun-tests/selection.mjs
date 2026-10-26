import { invokePython } from "./python.mjs";

export const planAffectedTests = (options = {}) => invokePython("plan", { options });
export const readTestSelection = (path, options = {}) => invokePython("read-plan", { path, options });
export const safePath = value => typeof value === "string" && invokePython("safe-path", { value });
