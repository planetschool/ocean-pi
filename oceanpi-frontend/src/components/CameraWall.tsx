// CameraWall.tsx
import React from "react";
import RTSPStream from "./RTSPStream";

const CameraWall: React.FC = () => {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
      <div className="aspect-video">
        <RTSPStream url="http://192.168.1.87:8888/hls/cam.m3u8" />
      </div>
      <div className="aspect-video">
        <RTSPStream url="http://192.168.1.74:8888/hls/cam.m3u8" />
      </div>
    </div>
  );
};

export default CameraWall;
