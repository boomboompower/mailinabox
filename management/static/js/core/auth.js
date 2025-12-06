/**
 * Authentication module
 * Manages user credentials and session
 */

import { state, setState } from './state.js';
import { api } from './api.js';
import { showPanel } from './router.js';
import { updateMenuVisibility } from './ui.js';

/**
 * Load stored credentials from storage
 */
export const loadStoredCredentials = async () => {
  try {
    let credentials = null;

    if (typeof sessionStorage !== 'undefined' && sessionStorage.getItem('miab-cp-credentials')) {
      credentials = JSON.parse(sessionStorage.getItem('miab-cp-credentials'));
    } else if (typeof localStorage !== 'undefined' && localStorage.getItem('miab-cp-credentials')) {
      credentials = JSON.parse(localStorage.getItem('miab-cp-credentials'));
    }

    // if credentials exist, validate them before setting state
    if (credentials) {
        // Temporarily set credentials for the validation API call
        setState({ credentials });

        // Validate credentials by making a test API call to /whoami
        // Don't set state optimistically - wait for validation
        const isValid = await new Promise((resolve) => {
            api('/whoami', 'GET', null,
                () => {
                    // valid credentials
                    resolve(true);
                },
                () => {
                    // invalid credentials
                    resolve(false);
                },
                {}, // headers
                true // skipAuthRedirect - we handle auth ourselves during validation
            );
        });

        if (!isValid) {
            // Clear invalid credentials from storage and state
            clear();
        }
    }
  } catch (e) {
    console.error('Failed to load credentials:', e);
    clear();
  }
};

/**
 * Save credentials to storage
 * @type {(credentials: any, remember: boolean) => void}
 */
export const saveCredentials = (credentials, remember = false) => {
  setState({ credentials });

  const credsJson = JSON.stringify(credentials);
  if (remember) {
    localStorage.setItem('miab-cp-credentials', credsJson);
    sessionStorage.removeItem('miab-cp-credentials');
  } else {
    sessionStorage.setItem('miab-cp-credentials', credsJson);
    localStorage.removeItem('miab-cp-credentials');
  }
};

/**
 * Clear stored credentials
 */
export const clear = () => {
  setState({ credentials: null });
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem('miab-cp-credentials');
  }
  if (typeof sessionStorage !== 'undefined') {
    sessionStorage.removeItem('miab-cp-credentials');
  }
};

/**
 * Logout user
 */
export const logout = () => {
  api('/logout', 'POST');
  clear();
  showPanel('login');
  // remove '#logout' from URL if present
  window.location.hash = '';
  updateMenuVisibility();
};
