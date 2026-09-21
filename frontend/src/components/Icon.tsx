type IconProps = {
  name: 'inbox' | 'review' | 'left' | 'right' | 'down' | 'download' | 'refresh' | 'mail' | 'check' | 'warning' | 'external' | 'document' | 'search' | 'archive';
  className?: string;
};

export default function Icon({name, className = ''}: IconProps) {
  return <img className={`ui-icon ${className}`.trim()} src={`/icons/${name}.png`} alt="" aria-hidden="true"/>;
}
