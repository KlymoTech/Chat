import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Modal } from './ui';

let nextFrame: FrameRequestCallback | undefined;
const close = vi.fn();
beforeEach(() => {
  close.mockReset();
  nextFrame = undefined;
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    nextFrame = callback;
    return 1;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => { nextFrame = undefined; });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function flushFrame() {
  act(() => { const callback = nextFrame; nextFrame = undefined; callback?.(16); });
}

it('keeps an autofocus field focused when the delayed modal focus runs', () => {
  render(<Modal open onClose={close} title="Create an AI agent"><input aria-label="Agent name" autoFocus /></Modal>);
  expect(screen.getByRole('textbox', { name: 'Agent name' })).toHaveFocus();
  flushFrame();
  expect(screen.getByRole('textbox', { name: 'Agent name' })).toHaveFocus();
});

it('does not steal focus mid-entry or turn a typed space into Close', async () => {
  const user = userEvent.setup();
  render(<Modal open onClose={close} title="Create an AI agent"><input aria-label="Agent name" /></Modal>);
  const input = screen.getByRole('textbox', { name: 'Agent name' });
  await user.type(input, 'Hindi');
  flushFrame();
  await user.keyboard(' Lead Agent');
  expect(input).toHaveValue('Hindi Lead Agent');
  expect(close).not.toHaveBeenCalled();
});

it('still focuses the first control, traps Tab and closes on Escape without a field focus', async () => {
  const user = userEvent.setup();
  render(<Modal open onClose={close} title="Confirmation" footer={<button>Confirm</button>}><p>Review the operation.</p></Modal>);
  flushFrame();
  expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus();
  await user.tab({ shift: true });
  expect(screen.getByRole('button', { name: 'Confirm' })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus();
  await user.keyboard('{Escape}');
  expect(close).toHaveBeenCalledTimes(1);
});
