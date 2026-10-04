import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

window.scrollTo = () => {};
window.alert = vi.fn();
window.confirm = vi.fn(() => true);
afterEach(() => { cleanup(); localStorage.clear(); window.alert.mockClear(); });
