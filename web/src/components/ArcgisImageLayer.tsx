import { createLayerComponent, type LeafletContextInterface } from "@react-leaflet/core";
import type { ImageMapLayer, ImageMapLayerOptions } from "esri-leaflet";
import { imageMapLayer } from "esri-leaflet";

export interface ArcgisImageLayerProps extends ImageMapLayerOptions {
  url: string;
}

const createImageLayer = (
  props: ArcgisImageLayerProps,
  context: LeafletContextInterface
) => {
  const { url, ...options } = props;
  const instance = imageMapLayer({ url, ...options });
  return {
    instance,
    context,
  };
};

const updateImageLayer = (
  instance: ImageMapLayer,
  props: ArcgisImageLayerProps,
  prevProps: ArcgisImageLayerProps
) => {
  if (props.opacity !== prevProps.opacity && typeof props.opacity === "number") {
    instance.setOpacity(props.opacity);
  }
  if (props.zIndex !== prevProps.zIndex && typeof props.zIndex === "number") {
    instance.setZIndex(props.zIndex);
  }
};

export const ArcgisImageLayer = createLayerComponent<ImageMapLayer, ArcgisImageLayerProps>(
  createImageLayer,
  updateImageLayer
);
