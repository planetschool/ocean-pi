import React, { useEffect, useState } from "react";
import axios from "axios";
import "./App.css";

function App() {
  const [atmosphereData, setAtmosphereData] = useState(null);
  const [signalkData, setSignalkData] = useState(null);

  useEffect(() => {
    const fetchData = () => {
      axios
        .get("http://192.168.1.77:5000/api/atmosphere")
        .then((res) => setAtmosphereData(res.data))
        .catch((err) => console.error("Atmosphere error:", err));

      axios
        .get("http://192.168.1.77:5000/api/signalk")
        .then((res) => setSignalkData(res.data))
        .catch((err) => console.error("SignalK error:", err));
    };

    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="App" style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>🌊 Ocean Pi Dashboard</h1>

      <div style={{ display: "flex", gap: "1rem", marginBottom: "2rem" }}>
        <div style={{ flex: 1 }}>
          <h2>Camera Stream 1</h2>
          <video
            src="http://192.168.1.74:8888/cam/index.m3u8"
            controls
            autoPlay
            muted
            style={{ width: "100%" }}
          />
        </div>
        <div style={{ flex: 1 }}>
          <h2>Camera Stream 2</h2>
          <video
            src="http://192.168.1.87:8888/cam/index.m3u8"
            controls
            autoPlay
            muted
            style={{ width: "100%" }}
          />
        </div>
      </div>

      <h2>Atmosphere Sensor Data</h2>
      {!atmosphereData ? (
        <p>Loading...</p>
      ) : (
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <div className="card">
            <h3>Temperature</h3>
            <p>{atmosphereData.scd41_temperature_F} °F</p>
          </div>
          <div className="card">
            <h3>Humidity</h3>
            <p>{atmosphereData.scd41_humidity_} %</p>
          </div>
          <div className="card">
            <h3>CO₂</h3>
            <p>{atmosphereData.scd41_co2_ppm} ppm</p>
          </div>
          <div className="card">
            <h3>Pressure</h3>
            <p>{atmosphereData.bmp388_pressure_hpa} hPa</p>
          </div>
          <div className="card">
            <h3>Light</h3>
            <p>{atmosphereData.tsl2591_lux} lux</p>
          </div>
        </div>
      )}

      <h2 style={{ marginTop: "2rem" }}>SignalK Data</h2>
      {!signalkData ? (
        <p>Loading...</p>
      ) : (
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <div className="card">
            <h3>Wind Speed (True)</h3>
            <p>{signalkData["environment.wind.speedOverGround"]} m/s</p>
          </div>
          <div className="card">
            <h3>Outside Temperature</h3>
            <p>{signalkData["environment.outside.temperature"]} K</p>
          </div>
          <div className="card">
            <h3>Atmospheric Pressure</h3>
            <p>{signalkData["environment.outside.pressure"]} Pa</p>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
