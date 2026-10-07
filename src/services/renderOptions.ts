// "Make everything again" is chosen in the Generate dialog but acted on by RenderOverlay when its effect starts the render.
// It is read once: a retry after a failure goes back to reusing what was already made.
let forceNext = false;

export const requestForcedRender = (force: boolean) => {
  forceNext = force;
};

export const takeForcedRender = (): boolean => {
  const force = forceNext;
  forceNext = false;
  return force;
};
