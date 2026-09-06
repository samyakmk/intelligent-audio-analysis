import { describe, expect, it } from 'vitest';

import { mobileContentPadding } from './layout';

describe('responsive shell spacing', () => {
  it('keeps content below the mobile header and above bottom navigation', () => {
    expect(mobileContentPadding(47, 34)).toEqual({ paddingTop: 123, paddingBottom: 130 });
  });

  it('does not accept negative safe-area values', () => {
    expect(mobileContentPadding(-1, -1)).toEqual({ paddingTop: 76, paddingBottom: 96 });
  });
});
