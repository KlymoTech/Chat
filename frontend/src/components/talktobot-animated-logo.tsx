import { useEffect, useRef, useState } from 'react';

export type TalkToBotLogoState = 'idle' | 'thinking' | 'delighted' | 'confused' | 'angry';

const animationSources: Record<'entry' | TalkToBotLogoState, string> = {
  entry: '/bot-animations/entry.mp4',
  idle: '/bot-animations/sleep.mp4',
  thinking: '/bot-animations/focused.mp4',
  delighted: '/bot-animations/delighted.mp4',
  confused: '/bot-animations/confused.mp4',
  angry: '/bot-animations/angry.mp4',
};

const oneShotStates = new Set(['entry', 'delighted', 'confused', 'angry']);

export function TalkToBotAnimatedLogo({ state = 'idle', size, className = '', onStateComplete }: { state?: TalkToBotLogoState; size?: number | string; className?: string; onStateComplete?: () => void }) {
  const [visibleState, setVisibleState] = useState<'entry' | TalkToBotLogoState>('entry');
  const [failed, setFailed] = useState(false);
  const videos = useRef<Partial<Record<'entry' | TalkToBotLogoState, HTMLVideoElement>>>({});
  const requestedState = useRef<TalkToBotLogoState>(state);

  useEffect(() => {
    if (requestedState.current === state) return;
    requestedState.current = state;
    setFailed(false);
    setVisibleState(state);
  }, [state]);
  useEffect(() => {
    const video = videos.current[visibleState];
    if (!video) return;
    video.currentTime = 0;
    void video.play().catch(() => setFailed(true));
  }, [visibleState]);

  return <span className={`talktobot-animated-logo ${className}`.trim()} style={size === undefined ? undefined : { width: size, height: size }} aria-hidden="true">
    {Object.entries(animationSources).map(([name, source]) => {
      const animationState = name as 'entry' | TalkToBotLogoState;
      return <video key={name} ref={(element) => { videos.current[animationState] = element ?? undefined; }} className={animationState === visibleState ? 'is-visible' : ''} src={source} muted playsInline preload="metadata" loop={!oneShotStates.has(animationState)} onError={() => { if (animationState === visibleState) setFailed(true); }} onEnded={() => { if (oneShotStates.has(animationState)) { setVisibleState('idle'); onStateComplete?.(); } }} />;
    })}
    <span className={`talktobot-animated-logo__fallback${failed ? ' is-visible' : ''}`}><svg viewBox="0 0 64 64"><path d="M32 6.5l5.6 19.9L57.5 32l-19.9 5.6L32 57.5l-5.6-19.9L6.5 32l19.9-5.6L32 6.5z" /><circle cx="32" cy="32" r="4.6" /></svg></span>
  </span>;
}
