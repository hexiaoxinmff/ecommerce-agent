/** 内联 SVG 图标集（轻量，无第三方图标库依赖） */

type IconProps = {
  size?: number;
  className?: string;
};

const base = (size: number | undefined, d: React.ReactNode, className?: string) => (
  <svg
    width={size ?? 20}
    height={size ?? 20}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden="true"
  >
    {d}
  </svg>
);

export const IconHome = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V21h14V9.5" />
      <path d="M9 21v-6h6v6" />
    </>
  ), className);

export const IconChart = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <path d="M4 20V4" />
      <path d="M4 20h16" />
      <rect x="7" y="12" width="3" height="5" rx="0.5" />
      <rect x="12" y="8" width="3" height="9" rx="0.5" />
      <rect x="17" y="5" width="3" height="12" rx="0.5" />
    </>
  ), className);

export const IconDatabase = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5" />
      <path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" />
    </>
  ), className);

export const IconHistory = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
      <path d="M12 7v5l3 2" />
    </>
  ), className);

export const IconSettings = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </>
  ), className);

export const IconSpark = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <path d="M12 2 14.5 9.5 22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z" />
    </>
  ), className);

export const IconTrendUp = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <path d="M3 17 9 11l4 4 8-8" />
      <path d="M15 7h6v6" />
    </>
  ), className);

export const IconTrendDown = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <path d="M3 7l6 6 4-4 8 8" />
      <path d="M15 17h6v-6" />
    </>
  ), className);

export const IconWallet = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <path d="M16 12h4" />
    </>
  ), className);

export const IconCart = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <circle cx="9" cy="20" r="1.4" />
      <circle cx="17" cy="20" r="1.4" />
      <path d="M3 3h2l2.6 12.5a1.5 1.5 0 0 0 1.5 1.2h7.8a1.5 1.5 0 0 0 1.5-1.2L20.5 8H6" />
    </>
  ), className);

export const IconUsers = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ), className);

export const IconPrice = ({ size, className }: IconProps) =>
  base(size, (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M14.5 9a2.4 2.4 0 0 0-2.4-1.7c-1.6 0-2.8 1-2.8 2.2 0 2.6 5.4 1.3 5.4 3.6 0 1.2-1.2 2.1-2.7 2.1a2.7 2.7 0 0 1-2.6-1.8" />
      <path d="M12 6v12" />
    </>
  ), className);

