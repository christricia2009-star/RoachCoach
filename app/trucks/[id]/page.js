"use client";

import { useParams } from "next/navigation";
import TruckDetail from "../../components/TruckDetail";

export default function TruckDetailPage() {
  const params = useParams();
  const truckId = params?.id;

  if (!truckId) return null;
  return <TruckDetail truckId={truckId} />;
}
