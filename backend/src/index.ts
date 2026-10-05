import express from 'express';
import { setupRoutes } from './routes';

const app = express();
const port = 3000;

setupRoutes(app);

app.listen(port, () => {
  console.log(`App listening on port ${port}`);
});   