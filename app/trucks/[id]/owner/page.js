"use client";

import { useParams } from "next/navigation";
import OwnerOrderBoard from "../../../components/OwnerOrderBoard";

export default function OwnerOrderBoardPage() {
  const params = useParams();
  const truckId = params?.id;

  if (!truckId) return null;
  return <OwnerOrderBoard truckId={truckId} />;
}
