/**
 * Global application state
 * Simple observable pattern for state management
 */

export const state = {
  credentials: null,
  currentPanel: null,
  switchBackToPanel: null
};

const listeners = new Set();

/**
 * Subscribe to state changes
 * @type {(listener: (state: typeof state) => void) => () => void}
 */
export const subscribe = (listener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/**
 * Update state and notify listeners
 * @type {(updates: Partial<typeof state>) => void}
 */
export const setState = (updates) => {
  Object.assign(state, updates);
  listeners.forEach(listener => listener(state));
};

/**
 * Get current state
 * @type {() => typeof state}
 */
export const getState = () => state;
