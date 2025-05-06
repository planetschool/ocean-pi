import React, { useEffect, useState } from "react";

const SensorFeed = () => {
  const [readings, setReadings] = useState([]);
  const [error, setError] = useState(null);

  const fetchReadings = async () => {
    try {
      const response = await fetch("https://flask-backend-y1v3.onrender.com/readings");
      if (!response.ok) throw new Error("Failed to fetch readings");
      const data = await response.json();
      setReadings(data);
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    fetchReadings();
    const interval = setInterval(fetchReadings, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ marginTop: "2rem" }}>
      <h2>MQTT Sensor Stream</h2>
      {error && <p style={{ color: "red" }}>{error}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ border: "1px solid #ccc", padding: "8px" }}>Timestamp</th>
            <th style={{ border: "1px solid #ccc", padding: "8px" }}>Topic</th>
            <th style={{ border: "1px solid #ccc", padding: "8px" }}>Payload</th>
          </tr>
        </thead>
        <tbody>
          {readings.map((r) => (
            <tr key={r.id}>
              <td style={{ border: "1px solid #ccc", padding: "8px" }}>
                {new Date(r.timestamp).toLocaleString()}
              </td>
              <td style={{ border: "1px solid #ccc", padding: "8px" }}>{r.topic}</td>
              <td style={{ border: "1px solid #ccc", padding: "8px" }}>{r.payload}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default SensorFeed;
