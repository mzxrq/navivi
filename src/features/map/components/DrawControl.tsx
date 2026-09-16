import MapboxDraw from '@mapbox/mapbox-gl-draw';
import { useControl } from 'react-map-gl/mapbox';
import type { ControlPosition } from 'react-map-gl/mapbox';

type DrawControlProps = ConstructorParameters<typeof MapboxDraw>[0] & {
  position?: ControlPosition;
  onCreate?: (evt: { features: any[] }) => void;
  onUpdate?: (evt: { features: any[]; action: string }) => void;
  onDelete?: (evt: { features: any[] }) => void;
};

export default function DrawControl(props: DrawControlProps) {
  useControl<MapboxDraw>(
    () => new MapboxDraw(props),
    ({ map }) => {
      map.on('draw.create', props.onCreate!);
      map.on('draw.update', props.onUpdate!);
      map.on('draw.delete', props.onDelete!);
    },
    ({ map }) => {
      map.off('draw.create', props.onCreate!);
      map.off('draw.update', props.onUpdate!);
      map.off('draw.delete', props.onDelete!);
    },
    {
      position: props.position
    }
  );

  return null;
}

