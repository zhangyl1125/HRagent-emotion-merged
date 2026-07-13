import boschLogo from '../assets/brand/bosch-logo.svg';

interface BrandProps {
  small?: boolean;
  showText?: boolean;
}

export function KonaLogo({ small = false }: { small?: boolean }) {
  return <span className={`bosch-wordmark-fallback ${small ? 'small' : ''}`} aria-hidden="true">BOSCH</span>;
}

export function Brand({ small = false, showText = true }: BrandProps) {
  return (
    <div className={`brand-lockup ${small ? 'small' : ''}`}>
      <img src={boschLogo} alt="Bosch" className="bosch-logo" />
      {/* {showText && <span className="brand-product-name">HR Conversation Coach</span>} */}
    </div>
  );
}
