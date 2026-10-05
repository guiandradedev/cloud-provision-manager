import { Express } from 'express';
import { ProvisionController } from './controllers/ProvisionController';

export function setupRoutes(app: Express) {
  app.get('/', (req: any, res: any) => {
    res.send('Hello World!');
  });

  const provisionController = new ProvisionController();
  app.get('/provision', provisionController.getProvisions)
  app.get('/provision/:id', provisionController.findProvision)
  app.post('/provision', provisionController.createProvision)
  app.put('/provision/:id', provisionController.updateProvision)
  app.delete('/provision/:id', provisionController.deleteProvision)

}