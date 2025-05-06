import React, { useEffect, useState } from "react";

const SensorFeed = () => {
  const [latestPayload, setLatestPayload] = useState(null);
  const [error, setError] = useState(null);

  const fetchReadings = async () => {
    try {
      const response = await fetch("https://flask-backend-y1v3.onrender.com/readings");
      if (!response.ok) throw new Error("Failed to fetch readings");
      const data = await response.json();

      const parsed = JSON.parse(data[0].payload); // assume newest reading
      setLatestPayload(parsed);
    } catch (err) {
      console.error(err);
      setError("Failed to load sensor data");
    }
  };

  useEffect(() => {
    fetchReadings();
    const interval = setInterval(fetchReadings, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ marginBottom: "2rem" }}>
      <h2>Atmosphere Sensor Data (Live MQTT)</h2>
      {error && <p style={{ color: "red" }}>{error}</p>}
      {!latestPayload ? (
        <p>Loading...</p>
      ) : (
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          {Object.entries(latestPayload).map(([key, value]) => (
            <div key={key} className="card">
              <h3>{key}</h3>
              <p>{value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default SensorFeed;
