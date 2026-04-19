export default {
  test: {
    environment: "node",
    include: ["src/**/*.test.js"],
    pool: "threads",
  },
};
