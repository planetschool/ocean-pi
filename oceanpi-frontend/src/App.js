import React, { useEffect, useState } from "react";
import axios from "axios";

function App() {
  const [atmosphereData, setAtmosphereData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchAtmosphereData = async () => {
      try {
        const response = await axios.get(
          "https://flask-backend-y1v3.onrender.com/readings"
        );
        setAtmosphereData(response.data);
        setError(null);
      } catch (err) {
        setError("Failed to fetch atmosphere data.");
        setAtmosphereData(null);
      }
    };

    fetchAtmosphereData();
    const interval = setInterval(fetchAtmosphereData, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>🌊 Ocean Pi Dashboard</h1>
      {error && <p style={{ color: "red" }}>{error}</p>}
      {!atmosphereData ? (
        <p>Loading atmosphere data...</p>
      ) : (
        <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "1fr 1fr" }}>
          <div className="card">
            <h3>CO₂ (ppm)</h3>
            <p>{atmosphereData.scd41_co2_ppm}</p>
          </div>
          <div className="card">
            <h3>Temp (°F)</h3>
            <p>{atmosphereData.scd41_temperature_F}</p>
          </div>
          <div className="card">
            <h3>Humidity (%)</h3>
            <p>{atmosphereData["scd41_humidity_%"]}</p>
          </div>
          <div className="card">
            <h3>Pressure (hPa)</h3>
            <p>{atmosphereData.bmp388_pressure_hpa}</p>
          </div>
          <div className="card">
            <h3>Light (lux)</h3>
            <p>{atmosphereData.tsl2591_lux}</p>
          </div>
          <div className="card">
            <h3>UV Index</h3>
            <p>{atmosphereData.ltr390_UV_index}</p>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
